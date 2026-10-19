"""Obtain the City of Austin purchase-order data and build the minimal public snapshot.

Privacy design (allowlist, not redaction)
-----------------------------------------
The original CSV (data/raw/, git-ignored, never published) contains vendor street addresses,
free-text item descriptions and contract names. The free text includes City staff names, phone
numbers, e-mail addresses, delivery addresses and at least one employee benefit purchase, so it
cannot be published safely by pattern-based redaction.

The public snapshot therefore keeps ONLY the analytical columns in `SNAPSHOT_COLUMNS`:

* no address, contact, contract-name or free-text description column is copied;
* vendors are identified by a pseudonymous `VENDOR_ID` (SHA-256 of the City vendor code);
  business names are published separately, only for vendors on the human-reviewed list
  `config/reviewed_vendor_names.csv`;
* an item description is represented only by `ITEM_TEXT_KEY`, the SHA-256 of the normalised
  text, and only when that text is on the human-reviewed product-specification list
  `config/reviewed_item_texts.csv` (which supplies a cleaned public label). Every other line
  has an empty key, so no hash of unreviewed private text is published;
* exact-duplicate detection is done on the full private row before columns are dropped
  (`RAW_EXACT_DUPLICATE`), so dropping columns cannot create false duplicates;
* NIGP class labels (the City's commodity taxonomy, not free text) are written to
  data/public/nigp_class_labels.csv for review.

`python -m supplierpulse.ingest --review` lists, from the private raw file, any candidate item
texts or vendor names that would appear in outputs but are not yet reviewed.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Settings

RAW_COLUMNS = [
    "COMMODITY", "COMMODITY_DESCRIPTION", "EXTENDED_DESCRIPTION", "QUANTITY",
    "UNIT_OF_MEASURE", "UNIT_OF_MEAS_DESC", "UNIT_PRICE", "ITM_TOT_AM",
    "MASTER_AGREEMENT", "CONTRACT_NAME", "PURCHASE_ORDER", "AWARD_DATE",
    "VENDOR_CODE", "LGL_NM", "AD_LN_1", "AD_LN_2", "CITY", "ST", "ZIP", "CTRY",
    "DATA_BUILD_DATE",
]
SNAPSHOT_COLUMNS = [
    "SOURCE_ROW", "PURCHASE_ORDER", "AWARD_DATE", "VENDOR_ID", "VENDOR_COUNTRY", "COMMODITY",
    "QUANTITY", "UNIT_OF_MEASURE", "UNIT_PRICE", "ITM_TOT_AM", "HAS_MASTER_AGREEMENT",
    "ITEM_TEXT_KEY", "RAW_EXACT_DUPLICATE", "DATA_BUILD_DATE",
]
EXCLUDED_SOURCE_COLUMNS = [c for c in RAW_COLUMNS if c not in {
    "PURCHASE_ORDER", "AWARD_DATE", "COMMODITY", "QUANTITY", "UNIT_OF_MEASURE", "UNIT_PRICE", "ITM_TOT_AM",
    "DATA_BUILD_DATE", "CTRY"}]


def raw_path(settings: Settings) -> Path:
    return settings.path("raw_dir") / settings.section("source.austin")["raw_filename"]


def snapshot_path(settings: Settings) -> Path:
    return settings.path("public_dir") / settings.section("source.austin")["snapshot_filename"]


def manifest_path(settings: Settings) -> Path:
    return settings.path("public_dir") / "SNAPSHOT_MANIFEST.json"


def class_labels_path(settings: Settings) -> Path:
    return settings.path("public_dir") / "nigp_class_labels.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vendor_id(code: str) -> str:
    return "V" + hashlib.sha256(code.encode("utf-8")).hexdigest()[:10].upper()


def normalise(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.upper().str.replace(r"\s+", " ", regex=True).str.strip()


def item_text(raw: pd.DataFrame) -> pd.Series:
    """Candidate item text: the extended description, or the City catalogue description for
    11-digit item-level codes when no extended description exists. Never published directly."""
    ext = normalise(raw["EXTENDED_DESCRIPTION"])
    catalogue = normalise(raw["COMMODITY_DESCRIPTION"]).where(raw["COMMODITY"].str.len() == 11, "")
    return ext.where(ext != "", catalogue)


def reviewed_item_texts(settings: Settings) -> pd.DataFrame:
    return pd.read_csv(settings.root / "config" / "reviewed_item_texts.csv", dtype=str)


def reviewed_vendor_names(settings: Settings) -> pd.DataFrame:
    return pd.read_csv(settings.root / "config" / "reviewed_vendor_names.csv", dtype=str)


def download_raw(settings: Settings) -> Path:
    """Download the full source CSV (about 100 MB) into data/raw/ (git-ignored)."""
    target = raw_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    url = settings.section("source.austin")["download_url"]
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=600) as resp, open(tmp, "wb") as out:  # noqa: S310 (fixed https URL from config)
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.replace(target)
    return target


def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Source schema changed; missing columns: {missing}")
    return df


def build_snapshot(settings: Settings) -> Path:
    src = raw_path(settings)
    if not src.exists():
        raise FileNotFoundError(f"{src} not found. Run `python -m supplierpulse.ingest --download` first.")
    raw = read_raw(src)
    reviewed = set(reviewed_item_texts(settings)["text_sha256"])
    keys = item_text(raw).map(text_hash)
    snap = pd.DataFrame({
        "SOURCE_ROW": np.arange(1, len(raw) + 1, dtype="int64"),
        "PURCHASE_ORDER": raw["PURCHASE_ORDER"],
        "AWARD_DATE": raw["AWARD_DATE"],
        "VENDOR_ID": raw["VENDOR_CODE"].map(vendor_id).where(raw["VENDOR_CODE"] != "", ""),
        "VENDOR_COUNTRY": raw["CTRY"],
        "COMMODITY": raw["COMMODITY"],
        "QUANTITY": raw["QUANTITY"],
        "UNIT_OF_MEASURE": raw["UNIT_OF_MEASURE"],
        "UNIT_PRICE": raw["UNIT_PRICE"],
        "ITM_TOT_AM": raw["ITM_TOT_AM"],
        "HAS_MASTER_AGREEMENT": raw["MASTER_AGREEMENT"].str.strip() != "",
        "ITEM_TEXT_KEY": keys.where(keys.isin(reviewed), ""),
        "RAW_EXACT_DUPLICATE": raw.duplicated(keep="first"),
        "DATA_BUILD_DATE": raw["DATA_BUILD_DATE"],
    })[SNAPSHOT_COLUMNS]
    out = snapshot_path(settings)
    out.parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(out, index=False, compression="zstd")

    # NIGP class labels from the City's commodity taxonomy (3-digit rows; else most common description)
    cls = raw["COMMODITY"].str[:3]
    official = raw[raw["COMMODITY"].str.len() == 3].groupby("COMMODITY")["COMMODITY_DESCRIPTION"].agg(lambda s: s.mode().iloc[0])
    common = raw.assign(cls=cls).groupby("cls")["COMMODITY_DESCRIPTION"].agg(lambda s: s.mode().iloc[0])
    labels = pd.DataFrame({
        "nigp_class": common.index,
        "source_label": [official.get(c, common[c]) for c in common.index],
        "label_source": ["class title in source data" if c in official.index else "most common item description in class"
                         for c in common.index],
    })
    labels.to_csv(class_labels_path(settings), index=False, encoding="utf-8")

    cfg = settings.section("source.austin")
    names = reviewed_vendor_names(settings)
    manifest = {
        "dataset": "Purchase Order Quantity Price detail for Commodity/Goods procurements",
        "publisher": "City of Austin, Texas (Austin Financial Services) via data.austintexas.gov",
        "landing_page": cfg["landing_page"],
        "download_url": cfg["download_url"],
        "terms_of_use": cfg["terms_url"],
        "license_summary": "City of Austin Open Data Terms of Use: data 'offered free and without restriction'; attribution requested, not required.",
        "source_data_build_dates": sorted(raw["DATA_BUILD_DATE"].unique().tolist()),
        "award_date_range": [str(pd.to_datetime(raw["AWARD_DATE"], format="%m/%d/%Y").min().date()),
                             str(pd.to_datetime(raw["AWARD_DATE"], format="%m/%d/%Y").max().date())],
        "raw_rows": int(len(raw)),
        "raw_sha256": sha256(src),
        "snapshot_file": out.name,
        "snapshot_rows": int(len(snap)),
        "snapshot_columns": SNAPSHOT_COLUMNS,
        "source_columns_not_published": EXCLUDED_SOURCE_COLUMNS,
        "transformations": [
            "VENDOR_CODE replaced by VENDOR_ID = 'V' + first 10 hex characters of SHA-256(VENDOR_CODE)",
            "MASTER_AGREEMENT reduced to HAS_MASTER_AGREEMENT (true/false)",
            "EXTENDED_DESCRIPTION / COMMODITY_DESCRIPTION reduced to ITEM_TEXT_KEY (SHA-256 of normalised text) "
            "only for texts on config/reviewed_item_texts.csv; empty otherwise",
            "RAW_EXACT_DUPLICATE computed on all 21 source columns before any column was dropped",
            "SOURCE_ROW added (1-based row number in the downloaded CSV)",
        ],
        "lines_with_reviewed_item_text": int((snap["ITEM_TEXT_KEY"] != "").sum()),
        "reviewed_item_texts": int(len(reviewed)),
        "reviewed_vendor_names": int(len(names)),
        "vendors_in_snapshot": int(snap["VENDOR_ID"].nunique()),
        "snapshot_created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    manifest_path(settings).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def load_snapshot(settings: Settings) -> pd.DataFrame:
    path = snapshot_path(settings)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Either restore it from the repository or run "
            "`python -m supplierpulse.ingest --download --snapshot`."
        )
    df = pd.read_parquet(path)
    missing = [c for c in SNAPSHOT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Snapshot is missing columns: {missing}")
    return df


def review_candidates(settings: Settings) -> dict:
    """From the PRIVATE raw file, list texts and vendors that could appear in outputs but are not reviewed.

    Item candidates: texts forming a like-for-like group (>= min lines per item-year, unit-priced,
    non-duplicate, focus window). Vendor candidates: top 150 vendors by focus-window spend plus the
    largest vendor in every NIGP class with focus spend >= the screening threshold.
    """
    raw = read_raw(raw_path(settings))
    a, p, c = settings.analysis, settings.price, settings.concentration
    award = pd.to_datetime(raw["AWARD_DATE"], format="%m/%d/%Y", errors="coerce")
    fy = award.dt.year + (award.dt.month >= a["fiscal_year_start_month"]).astype(int)
    amt = pd.to_numeric(raw["ITM_TOT_AM"], errors="coerce")
    qty = pd.to_numeric(raw["QUANTITY"], errors="coerce")
    price = pd.to_numeric(raw["UNIT_PRICE"], errors="coerce")
    unit_priced = (qty > 0) & (price > 0) & (raw["UNIT_OF_MEASURE"].str.strip() != "") & \
        ((qty * price - amt).abs() <= np.maximum(0.01, 0.005 * amt))
    focus = fy.between(a["focus_fy_start"], a["focus_fy_end"])
    text = item_text(raw)
    f = raw[unit_priced & focus & ~raw.duplicated(keep="first") & (text != "")].assign(
        text=text, uom=normalise(raw["UNIT_OF_MEASURE"]), fy=fy)
    groups = f.groupby(["COMMODITY", "uom", "text", "fy"]).size()
    cand_texts = sorted(groups[groups >= p["min_lines_per_item_year"]].index.get_level_values("text").unique())
    reviewed = set(reviewed_item_texts(settings)["text_sha256"])
    unreviewed_texts = [t for t in cand_texts if text_hash(t) not in reviewed]

    fr = raw[focus].assign(amt=amt[focus], cls=raw.loc[focus, "COMMODITY"].str[:3])
    spend = fr.groupby("VENDOR_CODE")["amt"].sum().sort_values(ascending=False)
    cls_spend = fr.groupby("cls")["amt"].sum()
    big = cls_spend[cls_spend >= c["min_category_spend"]].index
    top_cls = (fr[fr["cls"].isin(big)].groupby(["cls", "VENDOR_CODE"])["amt"].sum().reset_index()
               .sort_values(["cls", "amt"], ascending=[True, False]).groupby("cls").head(1)["VENDOR_CODE"])
    cand_vendors = set(spend.head(150).index) | set(top_cls)
    named = set(reviewed_vendor_names(settings)["vendor_id"])
    withheld = set(pd.read_csv(settings.root / "config" / "withheld_vendor_ids.csv", dtype=str)["vendor_id"])
    unreviewed_vendors = sorted(v for v in cand_vendors if vendor_id(v) not in named | withheld)
    return {"candidate_item_texts": len(cand_texts), "unreviewed_item_texts": unreviewed_texts,
            "candidate_vendors": len(cand_vendors), "unreviewed_vendor_codes": unreviewed_vendors}


def main() -> None:
    import argparse

    from .config import load_settings

    parser = argparse.ArgumentParser(description="Download City of Austin PO data and build the public snapshot.")
    parser.add_argument("--download", action="store_true", help="download the latest raw CSV into data/raw/")
    parser.add_argument("--snapshot", action="store_true", help="rebuild the minimal public snapshot from the raw CSV")
    parser.add_argument("--review", action="store_true", help="list unreviewed item texts / vendor names (local only)")
    args = parser.parse_args()
    settings = load_settings()
    if args.download:
        print(f"Downloaded {download_raw(settings)}")
    if args.snapshot:
        print(f"Wrote {build_snapshot(settings)}")
    if args.review:
        res = review_candidates(settings)
        print(f"Item texts: {res['candidate_item_texts']} candidates, {len(res['unreviewed_item_texts'])} unreviewed (excluded until reviewed)")
        print(f"Vendors: {res['candidate_vendors']} candidates, {len(res['unreviewed_vendor_codes'])} unreviewed (shown as pseudonymous IDs)")
        print("Unreviewed items are printed only to this local console; do not paste them into public files.")
        for t in res["unreviewed_item_texts"]:
            print("  ITEM  ", t[:160])
        for v in res["unreviewed_vendor_codes"]:
            print("  VENDOR", v)
    if not (args.download or args.snapshot or args.review):
        parser.print_help()


if __name__ == "__main__":
    main()
