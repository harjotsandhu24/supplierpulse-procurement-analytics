"""Load project configuration from config/settings.toml.

Every module receives a `Settings` object instead of reading paths or thresholds
directly, so the pipeline has no hard-coded local paths.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path
    raw: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        node: Any = self.raw
        for part in name.split("."):
            node = node[part]
        return node

    def path(self, key: str) -> Path:
        return self.root / self.raw["paths"][key]

    # Convenience accessors used throughout the package
    @property
    def analysis(self) -> dict[str, Any]:
        return self.raw["analysis"]

    @property
    def concentration(self) -> dict[str, Any]:
        return self.raw["concentration"]

    @property
    def price(self) -> dict[str, Any]:
        return self.raw["price"]

    @property
    def synthetic(self) -> dict[str, Any]:
        return self.raw["synthetic"]

    @property
    def scorecard(self) -> dict[str, Any]:
        return self.raw["scorecard"]

    @property
    def exceptions(self) -> dict[str, Any]:
        return self.raw["exceptions"]

    @property
    def scenario(self) -> dict[str, Any]:
        return self.raw["scenario"]

    def category_families(self) -> dict[str, str]:
        """Return {nigp_class: family}."""
        with open(self.root / "config" / "category_families.toml", "rb") as fh:
            families = tomllib.load(fh)["families"]
        mapping: dict[str, str] = {}
        for family, classes in families.items():
            for cls in classes:
                if cls in mapping:
                    raise ValueError(f"NIGP class {cls} is assigned to two families")
                mapping[cls] = family
        return mapping


def load_settings(root: Path | None = None) -> Settings:
    root = root or PROJECT_ROOT
    with open(root / "config" / "settings.toml", "rb") as fh:
        raw = tomllib.load(fh)
    weights = sum(raw["scorecard"][k] for k in raw["scorecard"] if k.startswith("weight_"))
    if abs(weights - 1.0) > 1e-9:
        raise ValueError(f"Scorecard weights must sum to 1.0, got {weights}")
    return Settings(root=root, raw=raw)
