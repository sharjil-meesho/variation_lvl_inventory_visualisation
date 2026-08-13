#!/usr/bin/env python3
"""
Build the data/ directory for the variation-level ROCE inventory explorer.

Inputs (raw Metabase JSON exports, produced via the packed array_agg queries):
  var_lvl_main_export.json   - 72,397 rows: one per qualifying PID x SID x Variation
                                (meesho_drr>=1 AND total_drr>=1), each with a packed
                                day-on-day series (offsets/inv/dispatched/ordered/overall as
                                CSV strings — "overall" = inventory-drop-derived order count,
                                added 2026-08-08, sign already flipped positive in the SQL),
                                PLUS (2026-08-13) all 64 columns from
                                scrap.roce_eqn__products_classification — see RAW_COLS below.
  var_lvl_dead_export.json   - 109,460 rows: deterministic 10-per-seller dead PID x Variation
                                sample (is_dead=1, avg_inventory>0, days_in_stock>=5), each with
                                a packed live-inventory series. Source table swapped 2026-08-13
                                to scrap.roce_eqn__products_classification (confirmed identical
                                population to the old table under the same filter).
  var_lvl_rollup_export.json - 7,937 rows: seller-level ROCE rollup (2 variants: overall,
                                reliable_w_restock_filter).

Outputs (written under OUT_DIR):
  data/index.json               - browse/search index, one row per PID x SID (aggregated across
                                   its qualifying variations), plus "rawCols" (the 64 column
                                   names, in order, that each variation's "raw" array maps to —
                                   stored once here instead of repeated per shard record).
                                   Plain JSON, fetched once at load.
  data/shards/<p % NSHARDS>.json.gz
                                 - map "<pid>_<sid>" -> {p, s, dv, vars:[...]}, one entry per
                                   variation. Gzip-compressed; index.html decodes with
                                   DecompressionStream on fetch.
  data/sid_roce.json            - map "<sid>" -> [10 values] (2 ROCE variants x 5 fields each).
                                   Plain JSON, fetched once at load.
  data/dead/<s % NDEAD>.json.gz - map "<sid>" -> [ [pid, vid, vn, sscat, avg, dis, nr, drr, of, iv], ... ]
                                  Gzip-compressed.

NSHARDS / NDEAD must match the constants read by index.html.

2026-08-13 update — table swap + 3 new filters/tags + "all columns" panel:
  Base table for the main export swapped from scrap.roce_eqn__var_lvl_calcs_kri_enriched to
  scrap.roce_eqn__products_classification (confirmed identical population under the same
  meesho_drr>=1 & total_drr>=1 filter — 72,397 rows / 50,113 combos, unchanged). The new table
  adds is_new, meesho_demand_shape_tag, overall_demand_shape_tag (now used as sidebar filters,
  set per variation like "slp" is) plus ~28 supporting demand-shape diagnostic columns. All 64
  columns are passed through per variation as a compact positional "raw" array (see RAW_COLS)
  for the new "all columns" panel in index.html, positioned between the SKU-level ROCE
  breakdown and the seller-level ROCE panel.

  is_new/meesho_demand_shape_tag/overall_demand_shape_tag are set PER VARIATION, not per
  product — 5,305 of 50,113 combos (~10.6%) have variations that disagree on at least one of
  the three. Per user confirmation (2026-08-13), the sidebar filters use "matches if ANY
  variation qualifies" logic — same pattern as the "db" (dead_basis) filter field on the
  sibling roce_inventory_var_lvl_new_dead site. See the "isnew"/"mdst"/"odst" index_rows
  fields below (comma-joined unique values per combo).
"""
import gzip
import json
import os
import sys

IN_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "."

NSHARDS = 256
NDEAD = 64

ANCHOR = "2026-04-01"

# All 64 columns of scrap.roce_eqn__products_classification, in the table's natural (describe)
# order — confirmed via `describe scrap.roce_eqn__products_classification` on 2026-08-13. Each
# variation's "raw" array (below) holds one value per entry here, in this exact order; index.json
# carries this list once (as "rawCols") so index.html can label the values without repeating
# 64 keys per variation record.
RAW_COLS = [
    "product_id", "supplier_id", "variation_id", "variation",
    "biz_fin_category", "sscat", "portfolio", "super_portfolio",
    "total_drr", "meesho_drr", "days_observed", "days_in_stock", "avg_inventory",
    "min_inventory", "inv_std", "n_restocks", "safety_stock", "cycle_stock",
    "restock_interval", "dio_safety", "dio_cycle", "dio_transit", "dio_pipeline",
    "total_orders", "is_dead", "dso", "odnr_frac", "nbyg_frac", "supplier_priority",
    "slp", "group_id", "pid_created", "category_group", "first_order_date", "span_days",
    "is_new", "max_daily_orders", "active_window_days", "zero_days",
    "early_mean", "mid_mean", "recent_mean", "early_stddev", "mid_stddev",
    "z_shift_recent_vs_mid", "z_shift_mid_vs_early",
    "abs_shift_recent_vs_mid", "abs_shift_mid_vs_early", "daily_cv",
    "overall_total_orders", "overall_max_daily_orders", "overall_zero_days",
    "overall_early_mean", "overall_mid_mean", "overall_recent_mean",
    "overall_early_stddev", "overall_mid_stddev",
    "overall_z_shift_recent_vs_mid", "overall_z_shift_mid_vs_early",
    "overall_abs_shift_recent_vs_mid", "overall_abs_shift_mid_vs_early", "overall_daily_cv",
    "meesho_demand_shape_tag", "overall_demand_shape_tag",
]


def load(name):
    path = os.path.join(IN_DIR, name)
    with open(path) as f:
        return json.load(f)


def _round_raw(v):
    # The warehouse returns most doubles at full float precision (15-17 significant digits,
    # e.g. 0.42673992673992656) — noise well beyond what anyone reads on the "all columns"
    # panel. Rounding to 4 decimal places here (same precision index.html already displays)
    # cuts data/shards/*.json.gz roughly in half with no loss of anything a person would
    # actually look at; it does NOT drop or omit any of the 64 columns.
    if isinstance(v, float):
        return round(v, 4)
    return v


def main():
    print("loading raw exports...")
    main_rows = load("var_lvl_main_export.json")
    dead_rows = load("var_lvl_dead_export.json")
    rollup_rows = load("var_lvl_rollup_export.json")
    print(f"  main={len(main_rows)} dead={len(dead_rows)} rollup={len(rollup_rows)}")

    os.makedirs(os.path.join(OUT_DIR, "data", "shards"), exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "data", "dead"), exist_ok=True)

    # ---- shards: group main_rows by (product_id, supplier_id) ----
    combos = {}  # (p,s) -> list of variation dict
    for r in main_rows:
        p, s = r["product_id"], r["supplier_id"]
        combos.setdefault((p, s), []).append(r)

    shard_buckets = [dict() for _ in range(NSHARDS)]
    index_rows = []

    for (p, s), vrows in combos.items():
        shard_idx = p % NSHARDS
        key = f"{p}_{s}"

        var_list = []
        for r in vrows:
            var_list.append({
                "vid": r["variation_id"],
                "vn": r.get("variation"),
                "drr": r.get("total_drr"),
                "mdrr": r.get("meesho_drr"),
                "avg": r.get("avg_inventory"),
                "min": r.get("min_inventory"),
                "std": r.get("inv_std"),
                "nr": r.get("n_restocks"),
                "saf": r.get("safety_stock"),
                "cyc": r.get("cycle_stock"),
                "ri": r.get("restock_interval"),
                "dsaf": r.get("dio_safety"),
                "dcyc": r.get("dio_cycle"),
                "dtr": r.get("dio_transit"),
                "dpipe": r.get("dio_pipeline"),
                "dso": r.get("dso"),
                "orders": r.get("total_orders"),
                "odnr": r.get("odnr_frac"),
                "nbyg": r.get("nbyg_frac"),
                "slp": r.get("slp"),
                "new": r.get("is_new"),
                "mdst": r.get("meesho_demand_shape_tag"),
                "odst": r.get("overall_demand_shape_tag"),
                "raw": [_round_raw(r.get(c)) for c in RAW_COLS],
                "of": r.get("offsets", ""),
                "iv": r.get("inv", ""),
                "pl": r.get("ordered", ""),
                "dp": r.get("dispatched", ""),
                "ov": r.get("overall", ""),
            })

        # default variation = highest total_orders (ties broken by highest drr)
        default_var = max(
            var_list,
            key=lambda v: (v["orders"] or 0, v["drr"] or 0),
        )

        first = vrows[0]

        shard_buckets[shard_idx][key] = {
            "p": p,
            "s": s,
            "spri": first.get("supplier_priority"),
            "dv": default_var["vid"],
            "vars": var_list,
        }

        # combo-level filter fields for is_new / meesho_demand_shape_tag / overall_demand_shape_tag:
        # comma-joined unique values across this combo's variations, so the sidebar filter can
        # match "any variation qualifies" (mirrors the "db"/dead_basis field on the sibling
        # roce_inventory_var_lvl_new_dead site — ~10.6% of combos here disagree across variations,
        # a very similar rate to that site's 5.5%).
        isnew_vals = sorted({str(r.get("is_new")) for r in vrows if r.get("is_new") is not None})
        mdst_vals = sorted({r.get("meesho_demand_shape_tag") for r in vrows if r.get("meesho_demand_shape_tag")})
        odst_vals = sorted({r.get("overall_demand_shape_tag") for r in vrows if r.get("overall_demand_shape_tag")})

        index_rows.append({
            "p": p,
            "s": s,
            "sc": first.get("sscat"),
            "pf": first.get("portfolio"),
            "sp": first.get("super_portfolio"),
            "bf": first.get("biz_fin_category"),
            "spri": first.get("supplier_priority"),
            "drr": sum((r.get("total_drr") or 0) for r in vrows),
            "mdrr": sum((r.get("meesho_drr") or 0) for r in vrows),
            "avg": sum((r.get("avg_inventory") or 0) for r in vrows),
            "nr": sum((r.get("n_restocks") or 0) for r in vrows),
            "dis": max((r.get("days_in_stock") or 0) for r in vrows),
            "to": sum((r.get("total_orders") or 0) for r in vrows),
            "nv": len(vrows),
            "dv": default_var["vid"],
            "isnew": ",".join(isnew_vals),
            "mdst": ",".join(mdst_vals),
            "odst": ",".join(odst_vals),
        })

    print(f"  {len(combos)} PID x SID combos, {len(main_rows)} variation rows")

    # ---- write shards (gzip-compressed; index.html decodes via DecompressionStream) ----
    for i, bucket in enumerate(shard_buckets):
        if not bucket:
            continue
        payload = json.dumps(bucket, separators=(",", ":")).encode("utf-8")
        with open(os.path.join(OUT_DIR, "data", "shards", f"{i}.json.gz"), "wb") as f:
            f.write(gzip.compress(payload, compresslevel=9))

    # ---- write index.json ----
    cols = ["p", "s", "sc", "pf", "sp", "bf", "spri", "drr", "mdrr", "avg", "nr", "dis", "to", "nv", "dv",
            "isnew", "mdst", "odst"]
    rows = [[r[c] for c in cols] for r in index_rows]
    index_doc = {
        "anchor": ANCHOR,
        "nshards": NSHARDS,
        "cols": cols,
        "rows": rows,
        "rawCols": RAW_COLS,
    }
    with open(os.path.join(OUT_DIR, "data", "index.json"), "w") as f:
        json.dump(index_doc, f, separators=(",", ":"))
    print(f"  wrote index.json: {len(rows)} combos")

    # ---- sid_roce.json ----
    sid_roce = {}
    field_order = [
        "overall_roce", "overall_roce_dio_cycle", "overall_roce_dio_transit",
        "overall_roce_dio_safety", "overall_roce_dso",
        "reliable_roce_w_restock_filter", "reliable_roce_w_restock_filter_dio_cycle",
        "reliable_roce_w_restock_filter_dio_transit", "reliable_roce_w_restock_filter_dio_safety",
        "reliable_roce_w_restock_filter_dso",
    ]
    for r in rollup_rows:
        sid_roce[str(r["supplier_id"])] = [r.get(f) for f in field_order]
    with open(os.path.join(OUT_DIR, "data", "sid_roce.json"), "w") as f:
        json.dump(sid_roce, f, separators=(",", ":"))
    print(f"  wrote sid_roce.json: {len(sid_roce)} sellers")

    # ---- dead/*.json ----
    dead_buckets = [dict() for _ in range(NDEAD)]
    dead_by_sid = {}
    for r in dead_rows:
        dead_by_sid.setdefault(r["supplier_id"], []).append(r)

    n_dead_written = 0
    for sid, rows_ in dead_by_sid.items():
        shard_idx = sid % NDEAD
        arr = []
        for r in rows_:
            arr.append([
                r["product_id"],
                r["variation_id"],
                r.get("variation"),
                r.get("sscat"),
                r.get("avg_inventory"),
                r.get("days_in_stock"),
                r.get("n_restocks"),
                r.get("total_drr"),
                r.get("offsets", ""),
                r.get("inv", ""),
            ])
            n_dead_written += 1
        dead_buckets[shard_idx][str(sid)] = arr

    for i, bucket in enumerate(dead_buckets):
        if not bucket:
            continue
        payload = json.dumps(bucket, separators=(",", ":")).encode("utf-8")
        with open(os.path.join(OUT_DIR, "data", "dead", f"{i}.json.gz"), "wb") as f:
            f.write(gzip.compress(payload, compresslevel=9))
    print(f"  wrote dead/*.json: {n_dead_written} dead combos across {len(dead_by_sid)} sellers")

    print("done.")


if __name__ == "__main__":
    main()
