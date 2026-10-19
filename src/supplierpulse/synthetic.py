"""Part B: deterministic SYNTHETIC purchase-order and goods-receipt data.

Why this exists
---------------
The City of Austin data (Part A) records what was ordered, from whom and at what price, but
not when goods were promised or received. Supplier delivery performance (on-time, in-full,
OTIF, lead-time variability, open/overdue orders, partial receipts, quality rejections) cannot
be measured from it. This module generates a separate, clearly labelled demonstration dataset
so those methods can be shown end to end.

Safeguards
----------
* Suppliers are anonymous codes ("SUP-01") with the name "Synthetic Supplier 01". No synthetic
  record refers to, or is derived from, any real vendor in the Austin data.
* Every table carries `data_origin = "SYNTHETIC"`.
* Supplier behaviour is set by explicit, documented profiles (below), so every pattern the
  dashboard shows is a designed property of the simulation, not a real-world observation.
* A fixed seed makes every run byte-for-byte identical.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statistics import NormalDist

from .config import Settings

ORIGIN = "SYNTHETIC"

CATEGORIES = {
    "ELEC": ("Electrical components", 14),
    "FLEET": ("Fleet parts", 10),
    "MRO": ("MRO & facilities supplies", 7),
    "PPE": ("Safety & PPE", 9),
    "CHEM": ("Water treatment chemicals", 12),
    "IT": ("IT peripherals", 8),
}  # code: (name, typical quoted lead time in days)

ITEMS = {
    "ELEC": [("Circuit breaker 20A", "EA", 38.0), ("Conduit fitting 1in", "EA", 4.2), ("Copper wire 12AWG", "RL", 96.0),
             ("LED fixture 4ft", "EA", 72.0), ("Junction box steel", "EA", 11.5), ("Meter socket 200A", "EA", 145.0),
             ("Fuse link 15K", "EA", 9.8), ("Cable tie 14in", "BAG", 18.0)],
    "FLEET": [("Brake pad set", "SET", 64.0), ("Oil filter", "EA", 7.5), ("Air filter", "EA", 21.0),
              ("Wiper blade 22in", "EA", 9.0), ("Battery 12V group 31", "EA", 168.0), ("Serpentine belt", "EA", 33.0),
              ("Headlamp assembly", "EA", 118.0), ("Hydraulic hose 3/8in", "FT", 6.4)],
    "MRO": [("Nitrile gloves case", "CASE", 52.0), ("Paper towel case", "CASE", 41.0), ("HVAC filter 20x25", "EA", 8.9),
            ("Floor cleaner 5gal", "PAIL", 58.0), ("Trash liner 40gal", "CASE", 36.0), ("Lamp T8 LED", "EA", 6.1),
            ("Padlock keyed", "EA", 14.0), ("Lubricant spray", "CAN", 7.2)],
    "PPE": [("Safety glasses", "PR", 4.8), ("Hi-vis vest class 2", "EA", 12.5), ("Hard hat type 1", "EA", 21.0),
            ("Ear plugs box", "BOX", 26.0), ("Cut-resistant gloves", "PR", 11.0), ("Safety boots", "PR", 115.0),
            ("Respirator N95 box", "BOX", 31.0), ("First aid kit", "EA", 64.0)],
    "CHEM": [("Sodium hypochlorite tote", "TOTE", 640.0), ("Ferric sulfate bulk", "TON", 410.0), ("Lime quick bulk", "TON", 265.0),
             ("Polymer flocculant drum", "DRUM", 820.0), ("Magnesium hydroxide tote", "TOTE", 930.0), ("Caustic soda drum", "DRUM", 380.0)],
    "IT": [("Docking station", "EA", 189.0), ("Monitor 24in", "EA", 162.0), ("Keyboard and mouse set", "SET", 38.0),
           ("USB-C cable 2m", "EA", 12.0), ("Network switch 24-port", "EA", 640.0), ("Laptop battery", "EA", 89.0),
           ("Rugged tablet case", "EA", 74.0), ("Label printer", "EA", 245.0)],
}


@dataclass(frozen=True)
class Profile:
    """Designed behaviour of one synthetic supplier (documented in docs/synthetic_data.md)."""
    supplier_id: str
    categories: tuple[str, ...]
    order_weight: float        # relative share of POs within its categories
    on_time_prob: float        # probability a line arrives by the quoted lead time (year 1)
    on_time_prob_y2: float     # same for year 2 (allows designed deterioration)
    lt_sd: float               # lead-time standard deviation, days (year 1)
    lt_sd_y2: float
    partial_prob: float        # probability a line ships in two parts
    short_close_prob: float    # probability a partial line never ships its remainder
    reject_event_prob: float   # probability a receipt has a quality rejection
    price_factor: float        # average paid price vs contracted standard price (1.0 = at contract)
    qty_scale: float = 1.0
    backorder_prob: float = 0.0  # probability a line is delayed a further 15-150 days (year 2 only unless backorder_all_years)
    backorder_all_years: bool = False
    max_pos: int | None = None # caps PO count to create small-sample suppliers
    design_note: str = ""


PROFILES = [
    Profile("SUP-01", ("ELEC",), 6.0, 0.93, 0.68, 2.0, 5.5, 0.06, 0.2, 0.02, 1.01, 1.6, backorder_prob=0.07,
            design_note="Largest electrical supplier; delivery deteriorates in year 2"),
    Profile("SUP-02", ("ELEC",), 3.0, 0.96, 0.96, 1.8, 1.8, 0.04, 0.1, 0.01, 1.00,
            design_note="Reliable electrical alternative with spare share"),
    Profile("SUP-03", ("ELEC",), 1.0, 0.85, 0.85, 3.0, 3.0, 0.05, 0.1, 0.02, 0.98, max_pos=6,
            design_note="Very few orders: tests the insufficient-evidence rule"),
    Profile("SUP-04", ("FLEET",), 3.0, 0.66, 0.64, 6.5, 7.0, 0.10, 0.3, 0.03, 0.99, backorder_prob=0.06, backorder_all_years=True,
            design_note="Chronically late fleet supplier with unstable lead times"),
    Profile("SUP-05", ("FLEET",), 3.0, 0.94, 0.95, 2.0, 2.0, 0.04, 0.1, 0.02, 1.02,
            design_note="Reliable fleet supplier"),
    Profile("SUP-14", ("FLEET",), 1.5, 0.88, 0.87, 3.0, 3.0, 0.06, 0.2, 0.06, 1.00,
            design_note="Mid-performing fleet supplier with occasional quality issues"),
    Profile("SUP-06", ("MRO",), 5.0, 0.98, 0.98, 1.0, 1.0, 0.03, 0.1, 0.005, 1.00,
            design_note="Excellent MRO supplier holding a large category share"),
    Profile("SUP-07", ("MRO",), 2.0, 0.90, 0.90, 2.0, 2.0, 0.32, 0.45, 0.01, 1.00, backorder_prob=0.03,
            design_note="Frequent split and short shipments"),
    Profile("SUP-08", ("MRO", "PPE"), 1.5, 0.91, 0.91, 2.0, 2.0, 0.05, 0.1, 0.01, 1.00,
            design_note="Generalist serving MRO and PPE"),
    Profile("SUP-09", ("CHEM",), 1.0, 0.95, 0.94, 1.5, 1.5, 0.03, 0.1, 0.01, 1.03, 1.0,
            design_note="Sole source for water treatment chemicals: good performance, high dependency"),
    Profile("SUP-10", ("PPE",), 2.0, 0.90, 0.89, 2.0, 2.0, 0.05, 0.1, 0.16, 0.97,
            design_note="Low price but recurring quality rejections"),
    Profile("SUP-11", ("PPE",), 2.0, 0.95, 0.95, 1.5, 1.5, 0.04, 0.1, 0.01, 1.01,
            design_note="Reliable PPE supplier"),
    Profile("SUP-12", ("IT",), 3.0, 0.90, 0.89, 2.5, 2.5, 0.05, 0.1, 0.01, 1.13,
            design_note="Paid prices drift well above contract"),
    Profile("SUP-13", ("IT",), 1.0, 0.96, 0.96, 1.5, 1.5, 0.03, 0.1, 0.01, 1.00, max_pos=10,
            design_note="Good IT supplier with a small, provisional sample"),
]


@dataclass
class SyntheticData:
    suppliers: pd.DataFrame
    categories: pd.DataFrame
    items: pd.DataFrame
    purchase_orders: pd.DataFrame
    po_lines: pd.DataFrame
    receipts: pd.DataFrame


def generate(settings: Settings) -> SyntheticData:
    cfg = settings.synthetic
    rng = np.random.default_rng(cfg["seed"])
    as_of = pd.Timestamp(cfg["as_of_date"])
    start = pd.Timestamp(cfg["start_date"])
    days = (as_of - start).days + 1
    midpoint = start + pd.DateOffset(years=1)

    categories = pd.DataFrame(
        [{"category_id": k, "category_name": v[0], "standard_lead_days": v[1], "data_origin": ORIGIN} for k, v in CATEGORIES.items()]
    )
    item_rows = []
    for cat, items in ITEMS.items():
        for i, (name, uom, price) in enumerate(items, start=1):
            item_rows.append({"item_id": f"{cat}-{i:02d}", "category_id": cat, "item_name": name, "uom": uom,
                              "standard_price": price, "data_origin": ORIGIN})
    items_df = pd.DataFrame(item_rows)

    suppliers = pd.DataFrame([{
        "supplier_id": p.supplier_id,
        "supplier_name": f"Synthetic Supplier {p.supplier_id[-2:]}",
        "primary_category_id": p.categories[0],
        "categories_served": ", ".join(p.categories),
        "design_note": p.design_note,
        "data_origin": ORIGIN,
    } for p in PROFILES]).sort_values("supplier_id").reset_index(drop=True)
    by_id = {p.supplier_id: p for p in PROFILES}

    # Quoted lead time per supplier-category is fixed so that, in year 1, the probability of
    # arriving by the quoted date equals the profile's on_time_prob.
    true_mean = {}
    quoted = {}
    for p in PROFILES:
        for cat in p.categories:
            mu = CATEGORIES[cat][1] + rng.integers(-1, 2)
            true_mean[(p.supplier_id, cat)] = mu
            quoted[(p.supplier_id, cat)] = int(round(mu + NormalDist().inv_cdf(p.on_time_prob) * p.lt_sd))

    # Purchase orders: category weights reflect a plausible mix of order volume.
    cat_weights = {"ELEC": 0.27, "FLEET": 0.22, "MRO": 0.20, "PPE": 0.12, "CHEM": 0.07, "IT": 0.12}
    cat_codes = list(cat_weights)
    po_rows, line_rows, receipt_rows = [], [], []
    po_count_by_supplier: dict[str, int] = {}
    n_pos = cfg["n_purchase_orders"]
    order_offsets = np.sort(rng.integers(0, days, size=n_pos))
    line_seq = 0
    receipt_seq = 0
    for n, offset in enumerate(order_offsets, start=1):
        order_date = start + pd.Timedelta(days=int(offset))
        cat = rng.choice(cat_codes, p=np.array(list(cat_weights.values())))
        eligible = [p for p in PROFILES if cat in p.categories
                    and (p.max_pos is None or po_count_by_supplier.get(p.supplier_id, 0) < p.max_pos)]
        w = np.array([p.order_weight for p in eligible])
        prof = eligible[int(rng.choice(len(eligible), p=w / w.sum()))]
        po_count_by_supplier[prof.supplier_id] = po_count_by_supplier.get(prof.supplier_id, 0) + 1
        po_id = f"SPO-{n:05d}"
        po_rows.append({"po_id": po_id, "supplier_id": prof.supplier_id, "category_id": cat,
                        "order_date": order_date, "data_origin": ORIGIN})

        cat_items = items_df[items_df["category_id"] == cat]
        n_lines = int(rng.choice([1, 2, 3, 4], p=[0.45, 0.30, 0.17, 0.08]))
        chosen = rng.choice(len(cat_items), size=min(n_lines, len(cat_items)), replace=False)
        year2 = order_date >= midpoint
        ot_prob = prof.on_time_prob_y2 if year2 else prof.on_time_prob
        sd = prof.lt_sd_y2 if year2 else prof.lt_sd
        mu = true_mean[(prof.supplier_id, cat)]
        # Shift the year-2 mean so the designed on-time probability holds against the unchanged quote.
        mu_eff = quoted[(prof.supplier_id, cat)] - NormalDist().inv_cdf(ot_prob) * sd if year2 else mu
        promised = order_date + pd.Timedelta(days=quoted[(prof.supplier_id, cat)])

        for line_no, idx in enumerate(chosen, start=1):
            item = cat_items.iloc[int(idx)]
            line_seq += 1
            line_id = f"{po_id}-{line_no}"
            base_qty = max(1.0, 1500.0 / item["standard_price"])
            qty = int(max(1, round(rng.lognormal(np.log(base_qty * prof.qty_scale), 0.5))))
            price = round(item["standard_price"] * prof.price_factor * rng.normal(1.0, 0.03), 2)
            cancelled = rng.random() < 0.02
            cancel_date = order_date + pd.Timedelta(days=int(rng.integers(1, 6))) if cancelled else pd.NaT
            if cancel_date is not pd.NaT and cancel_date > as_of:
                cancelled, cancel_date = False, pd.NaT
            line_rows.append({
                "po_line_id": line_id, "po_id": po_id, "line_number": line_no, "item_id": item["item_id"],
                "ordered_qty": qty, "unit_price": price, "standard_price": item["standard_price"],
                "promised_date": promised, "cancelled": bool(cancelled), "cancel_date": cancel_date,
                "short_closed": False, "data_origin": ORIGIN,
            })
            if cancelled:
                continue

            lead = max(1, int(round(rng.normal(mu_eff, sd))))
            if (year2 or prof.backorder_all_years) and rng.random() < prof.backorder_prob:
                lead += int(rng.integers(15, 151))  # designed backorder
            first_date = order_date + pd.Timedelta(days=lead)
            shipments: list[tuple[pd.Timestamp, int]] = []
            if qty > 1 and rng.random() < prof.partial_prob:
                first_qty = int(max(1, round(qty * rng.uniform(0.4, 0.8))))
                shipments.append((first_date, first_qty))
                if rng.random() < prof.short_close_prob:
                    line_rows[-1]["short_closed"] = True  # remainder never shipped; closed short 30 days after promise
                    line_rows[-1]["short_close_date"] = promised + pd.Timedelta(days=30)
                else:
                    shipments.append((first_date + pd.Timedelta(days=int(rng.integers(5, 21))), qty - first_qty))
            else:
                shipments.append((first_date, qty))

            for rdate, rqty in shipments:
                if rdate > as_of:
                    continue  # not yet received at the reporting date
                rejected = 0
                if rng.random() < prof.reject_event_prob:
                    rejected = int(max(1, round(rqty * rng.uniform(0.05, 0.30))))
                receipt_seq += 1
                receipt_rows.append({
                    "receipt_id": f"GR-{receipt_seq:06d}", "po_line_id": line_id, "receipt_date": rdate,
                    "received_qty": rqty, "rejected_qty": rejected, "accepted_qty": rqty - rejected,
                    "data_origin": ORIGIN,
                })

    po_lines = pd.DataFrame(line_rows)
    if "short_close_date" not in po_lines:
        po_lines["short_close_date"] = pd.NaT
    # A short-close only exists once its close date has passed the reporting date.
    not_yet = po_lines["short_closed"] & (po_lines["short_close_date"] > as_of)
    po_lines.loc[not_yet, ["short_closed", "short_close_date"]] = [False, pd.NaT]
    po_lines.loc[~po_lines["short_closed"], "short_close_date"] = pd.NaT
    po_lines = po_lines[[
        "po_line_id", "po_id", "line_number", "item_id", "ordered_qty", "unit_price", "standard_price",
        "promised_date", "cancelled", "cancel_date", "short_closed", "short_close_date", "data_origin",
    ]]
    return SyntheticData(
        suppliers=suppliers,
        categories=categories,
        items=items_df,
        purchase_orders=pd.DataFrame(po_rows),
        po_lines=po_lines,
        receipts=pd.DataFrame(receipt_rows),
    )


def as_of(settings: Settings) -> pd.Timestamp:
    return pd.Timestamp(settings.synthetic["as_of_date"])
