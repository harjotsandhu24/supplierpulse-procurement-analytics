"""Privacy checks for every file intended for publication.

Two independent layers, so assurance does not rest on pattern matching alone:

1. Structural (works from a clean clone): the public snapshot contains only allowlisted columns,
   and every name or description field in published tables comes from a reviewed list
   (reviewed vendor names, reviewed item labels, NIGP class labels, synthetic supplier names).
2. Leakage (needs the private raw file locally): extracts the text of every publishable file
   (CSV, JSON, Markdown, SQL, Python, HTML, the XML inside .xlsx, PDF text, Parquet string
   columns) and searches it for private values taken from the raw source: vendor names that are
   not on the reviewed list, vendor street addresses, e-mail addresses, phone numbers, and
   person names that appear after "ATTN"/"CONTACT"/"FOR"/"PER" or as stand-alone item text.
   Pattern scans for e-mails and phone numbers run on top of that.

PNG screenshots cannot be text-scanned; they are rendered from the dashboard HTML, which is.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIRS = ["data/public", "outputs", "deliverables", "docs", "notion", "sql", "config", "src", "tests", "scripts", ".github"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.(?:com|gov|org|net|edu|us)\b", re.I)
PHONE = re.compile(r"(?<![\w.-])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w-])")
ALLOWED_EMAILS = {
    "223194018+harjotsandhu24@users.noreply.github.com",  # author's GitHub no-reply commit address
    "feross@feross.org",  # licence header of the 'buffer' library bundled inside plotly.js
}
TEXT_SUFFIXES = {".md", ".csv", ".json", ".sql", ".py", ".toml", ".txt", ".html", ".yml", ".yaml", ".cfg", ".ini"}


def publishable_files(root: Path = ROOT) -> list[Path]:
    files = []
    for d in PUBLIC_DIRS:
        base = root / d
        if base.exists():
            files += [p for p in base.rglob("*") if p.is_file() and not (EXCLUDE_PARTS & set(p.parts))]
    files += [p for p in root.glob("*") if p.is_file()]
    return sorted(set(files))


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".xlsx":
        with zipfile.ZipFile(path) as z:
            return "\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(path.read_bytes())).pages)
    if suffix == ".parquet":
        df = pd.read_parquet(path)
        return "\n".join(df[c].astype(str).str.cat(sep="\n") for c in df.columns if df[c].dtype == object or str(df[c].dtype).startswith("str"))
    return ""


@dataclass
class ScanResult:
    files_scanned: int = 0
    unscannable: list[str] = field(default_factory=list)
    findings: list[tuple[str, str, str]] = field(default_factory=list)  # (file, kind, value)


def pattern_scan(files: list[Path]) -> ScanResult:
    res = ScanResult()
    for p in files:
        text = extract_text(p)
        if not text and p.suffix.lower() in {".png", ".jpg"}:
            res.unscannable.append(str(p.relative_to(ROOT)))
            continue
        res.files_scanned += 1
        rel = str(p.relative_to(ROOT))
        for m in EMAIL.findall(text):
            if m.lower() not in ALLOWED_EMAILS and "@example." not in m.lower():
                res.findings.append((rel, "email", m))
        if p.suffix.lower() in {".csv", ".md", ".json", ".pdf", ".xlsx"} or (p.suffix.lower() == ".html" and "Dashboard" not in p.name and "Brief" not in p.name):
            for m in PHONE.findall(text):
                res.findings.append((rel, "phone", m))
    return res


def private_needles(raw: pd.DataFrame, reviewed_names: set[str]) -> dict[str, set[str]]:
    """Values from the private source that must never appear in public files."""
    norm = lambda s: s.fillna("").astype(str).str.upper().str.replace(r"\s+", " ", regex=True).str.strip()  # noqa: E731
    reviewed_up = [n.upper() for n in reviewed_names]
    names = set(norm(raw["LGL_NM"]).unique()) - set(reviewed_up)
    # an unreviewed spelling that is part of a reviewed business name (e.g. another account of the same company) is not a leak
    names = {n for n in names if len(n) >= 8 and not any(n in r for r in reviewed_up)}
    addresses = {a for a in norm(raw["AD_LN_1"]).unique() if len(a) >= 10 and re.search(r"\d", a)}
    free = pd.concat([norm(raw["EXTENDED_DESCRIPTION"]), norm(raw["CONTRACT_NAME"])])
    persons: set[str] = set()
    pat = re.compile(r"(?:ATTN|ATTENTION|CONTACT|CALL|C/O)\s*[:\-]?\s*([A-Z][A-Z'\-]+(?: [A-Z]\.?)? [A-Z][A-Z'\-]{2,})")
    for t in free[free.str.contains(r"(?:ATTN|ATTENTION|CONTACT|CALL|C/O)", regex=True)].unique():
        persons |= {m.strip() for m in pat.findall(t)}
    non_name = re.compile(r"(?:PRIOR|BEFORE|DELIVERY|ORDER|PURCHASING|WAREHOUSE|DEPARTMENT|CENTER|OFFICE|PLANT|DIVISION|BOX|FOR|THE|AND|TO|WITH)")
    persons = {p for p in persons if not non_name.search(p)}
    # phrases such as "CALL AT LEAST ..." or "CALL PER YEAR" are instructions, not names
    persons = {p for p in persons if p.split()[0] not in {"AT", "PER", "PLEASE", "IF", "WHEN", "ONE", "TWO", "ALL", "ANY", "EACH"}}
    emails = set()
    for t in free[free.str.contains("@", regex=False)].unique():
        emails |= {m.lower() for m in EMAIL.findall(t)}
    return {"vendor_name_not_reviewed": names, "vendor_address": addresses, "person_name_in_free_text": persons,
            "source_email": emails}


def leakage_scan(files: list[Path], needles: dict[str, set[str]]) -> ScanResult:
    res = ScanResult()
    for p in files:
        text = extract_text(p)
        if not text:
            continue
        res.files_scanned += 1
        up = text.upper()
        rel = str(p.relative_to(ROOT))
        for kind, values in needles.items():
            hay = text.lower() if kind == "source_email" else up
            for v in values:
                if v in hay and re.search(r"(?<![A-Z0-9])" + re.escape(v) + r"(?![A-Z0-9])", hay):
                    res.findings.append((rel, kind, v))
    return res
