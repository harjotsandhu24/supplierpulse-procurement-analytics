"""Build the DuckDB analytical database and run the SQL query package.

Tables (documented in docs/data_dictionary.md):
  obs_po_line, obs_po_header, obs_vendor, obs_category, obs_excluded_line   -- City of Austin (observed)
  syn_supplier, syn_category, syn_item, syn_purchase_order, syn_po_line,
  syn_goods_receipt                                                           -- synthetic demonstration
  params                                                                      -- reporting parameters

The SQL queries in sql/queries/ compute their results from these base tables independently of
the pandas code; tests compare the two.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .config import Settings


def db_path(settings: Settings) -> Path:
    return settings.path("processed_dir") / "supplierpulse.duckdb"


def build_database(settings: Settings, model, excluded: pd.DataFrame, syn) -> Path:
    path = db_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    a = settings.analysis
    params = pd.DataFrame([{
        "as_of_date": pd.Timestamp(settings.synthetic["as_of_date"]),
        "on_time_grace_days": settings.synthetic["on_time_grace_days"],
        "in_full_tolerance": settings.synthetic["in_full_tolerance"],
        "focus_fy_start": a["focus_fy_start"], "focus_fy_end": a["focus_fy_end"],
        "min_category_spend": settings.concentration["min_category_spend"],
        "single_vendor_share": settings.concentration["single_vendor_share"],
        "hhi_highly_concentrated": settings.concentration["hhi_highly_concentrated"],
        "min_lines_per_item_year": settings.price["min_lines_per_item_year"],
        "above_baseline_ratio": settings.price["above_baseline_ratio"],
        **{k: v for k, v in settings.scorecard.items()},
        "min_completed_for_variability": settings.exceptions["min_completed_for_variability"],
        "high_dependency_category_share": settings.exceptions["high_dependency_category_share"],
        "high_dependency_total_share": settings.exceptions["high_dependency_total_share"],
        "medium_dependency_category_share": settings.exceptions["medium_dependency_category_share"],
        "medium_dependency_total_share": settings.exceptions["medium_dependency_total_share"],
    }])
    obs_line = model.lines.drop(columns=["vendor_name", "class_label", "spend_family"])
    tables = {
        "obs_po_line": obs_line,
        "obs_po_header": model.headers,
        "obs_vendor": model.vendors,
        "obs_category": model.categories,
        "obs_excluded_line": excluded,
        "syn_supplier": syn.suppliers,
        "syn_category": syn.categories,
        "syn_item": syn.items,
        "syn_purchase_order": syn.purchase_orders,
        "syn_po_line": syn.po_lines,
        "syn_goods_receipt": syn.receipts,
        "params": params,
    }
    con = duckdb.connect(str(path))
    try:
        for name, df in tables.items():
            con.register("tmp_df", df)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp_df")
            con.unregister("tmp_df")
        for view in sorted((settings.root / "sql" / "views").glob("*.sql")):
            con.execute(view.read_text(encoding="utf-8"))
    finally:
        con.close()
    return path


def query_files(settings: Settings) -> list[Path]:
    return sorted((settings.root / "sql" / "queries").glob("*.sql"))


def run_queries(settings: Settings, out_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    out_dir = out_dir or settings.root / "outputs" / "sql_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, pd.DataFrame] = {}
    con = duckdb.connect(str(db_path(settings)), read_only=True)
    try:
        for qf in query_files(settings):
            df = con.execute(qf.read_text(encoding="utf-8")).df()
            results[qf.stem] = df
            df.to_csv(out_dir / f"{qf.stem}.csv", index=False, float_format="%.6f")
    finally:
        con.close()
    return results


def main() -> None:
    from .config import load_settings

    settings = load_settings()
    for name, df in run_queries(settings).items():
        print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    main()
