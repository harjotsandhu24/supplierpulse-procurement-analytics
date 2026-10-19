from __future__ import annotations

import pandas as pd
import pytest

from supplierpulse import database, pipeline
from supplierpulse.config import load_settings
from supplierpulse.synthetic import SyntheticData


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def results(settings):
    """Full analysis on the committed public snapshot (the same inputs a clean clone has)."""
    return pipeline.analyse(settings)


@pytest.fixture(scope="session")
def db(settings, results):
    database.build_database(settings, results.model, results.clean.excluded, results.syn)
    return database.db_path(settings)


@pytest.fixture(scope="session")
def sql(settings, db):
    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    yield con
    con.close()


D = pd.Timestamp


def mini_synthetic() -> SyntheticData:
    """Hand-built order book with one line per edge case. As-of date: 2026-03-31.

    L1 full quantity on time                       -> OT, IF, OTIF
    L2 6 of 10 on time, 4 more 5 days late         -> OT, IF, not OTIF, 5 days late
    L3 cancelled                                   -> excluded everywhere
    L4 promised after as-of, nothing received      -> not due, excluded from rates
    L5 due, nothing received                       -> not OT/IF/OTIF, open & overdue, 31 days late
    L6 5 of 10 on time, then closed short          -> OT, not IF, not OTIF, not open
    L7 (supplier B) full but 2 days late, 3 of 20 rejected
    """
    suppliers = pd.DataFrame({"supplier_id": ["A", "B"], "supplier_name": ["Synthetic Supplier A", "Synthetic Supplier B"],
                              "primary_category_id": ["X", "X"], "categories_served": ["X", "X"], "design_note": ["", ""],
                              "data_origin": "SYNTHETIC"})
    pos = pd.DataFrame({"po_id": ["P1", "P2", "P3"], "supplier_id": ["A", "A", "B"], "category_id": ["X", "X", "X"],
                        "order_date": [D("2026-01-01"), D("2026-02-01"), D("2026-01-01")], "data_origin": "SYNTHETIC"})
    lines = pd.DataFrame({
        "po_line_id": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
        "po_id": ["P1", "P1", "P1", "P2", "P2", "P2", "P3"],
        "line_number": [1, 2, 3, 1, 2, 3, 1],
        "item_id": ["I"] * 7,
        "ordered_qty": [10, 10, 10, 10, 10, 10, 20],
        "unit_price": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.1],
        "standard_price": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.0],
        "promised_date": [D("2026-01-15"), D("2026-01-15"), D("2026-01-15"), D("2026-04-15"), D("2026-02-28"),
                          D("2026-02-15"), D("2026-01-10")],
        "cancelled": [False, False, True, False, False, False, False],
        "cancel_date": [pd.NaT, pd.NaT, D("2026-01-03"), pd.NaT, pd.NaT, pd.NaT, pd.NaT],
        "short_closed": [False, False, False, False, False, True, False],
        "short_close_date": [pd.NaT] * 5 + [D("2026-03-15"), pd.NaT],
        "data_origin": "SYNTHETIC",
    })
    receipts = pd.DataFrame({
        "receipt_id": ["R1", "R2", "R3", "R4", "R5"],
        "po_line_id": ["L1", "L2", "L2", "L6", "L7"],
        "receipt_date": [D("2026-01-14"), D("2026-01-15"), D("2026-01-20"), D("2026-02-10"), D("2026-01-12")],
        "received_qty": [10, 6, 4, 5, 20],
        "rejected_qty": [0, 0, 0, 0, 3],
        "accepted_qty": [10, 6, 4, 5, 17],
        "data_origin": "SYNTHETIC",
    })
    cats = pd.DataFrame({"category_id": ["X"], "category_name": ["Test"], "standard_lead_days": [10], "data_origin": "SYNTHETIC"})
    items = pd.DataFrame({"item_id": ["I"], "category_id": ["X"], "item_name": ["Item"], "uom": ["EA"], "standard_price": [2.0],
                          "data_origin": "SYNTHETIC"})
    return SyntheticData(suppliers, cats, items, pos, lines, receipts)


@pytest.fixture
def mini():
    return mini_synthetic()


MINI_AS_OF = D("2026-03-31")
