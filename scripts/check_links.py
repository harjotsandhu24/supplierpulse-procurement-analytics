"""Verify every relative link and image in the repository's Markdown files resolves to a file.

    python scripts/check_links.py

External http(s) links are listed but not fetched. `ADD-AFTER-PUBLISHING` placeholders in the
Notion package are reported separately (they are intentional until the repository is public).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".venv", ".git", "data", ".pytest_cache", "node_modules"}


def main() -> int:
    broken, external, placeholders, checked = [], set(), [], 0
    for md in ROOT.rglob("*.md"):
        if SKIP_DIRS & set(md.relative_to(ROOT).parts):
            continue
        for target in LINK.findall(md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                external.add(target)
                continue
            if target == "ADD-AFTER-PUBLISHING":
                placeholders.append(str(md.relative_to(ROOT)))
                continue
            path = target.split("#")[0]
            if not path:
                continue  # in-page anchor
            checked += 1
            if not (md.parent / path).resolve().exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    print(f"Relative links checked: {checked}; broken: {len(broken)}")
    for b in broken:
        print("  BROKEN", b)
    print(f"Intentional placeholders (publish first): {len(placeholders)} in {sorted(set(placeholders))}")
    print("External links (not fetched):")
    for e in sorted(external):
        print("  ", e)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
