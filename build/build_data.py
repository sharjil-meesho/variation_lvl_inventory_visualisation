#!/usr/bin/env python3
"""
Build the data/ directory for the variation-level ROCE inventory explorer — 2026-08-19 refresh
(updated later the same day, "2026-08-19b", to add the Reliable Inventory Curve filter).

This replaces the previous build (scrap.roce_eqn__products_classification +
scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders, Apr-Jun window, with a Seller ROCE rollup
panel and a Dead PID x Variations sample panel) with:
  - A new source table for all "static" per-variation metrics: scrap.roce_demand_eqn__enriched
    (86 columns as of 2026-08-19b — the user added is_unreliable_flat_inv, suspect_inv_levels,
    and is_unreliable_inv to this table after the initial 83-column refresh; no DRR floor either
    way — filtered instead by days_observed=90, instock_days>=45, order_days>=10).
  - 2026-08-19b addition: a "Reliable inventory curve" browse filter (Yes/No), sourced from the
    new is_unreliable_inv column (Yes = is_unreliable_inv=0). Same population as before — this
    only adds a column/filter, it does not change which PID x SID x Variation rows qualify. The
    supplemental pull for these 3 new columns was merged into roce_demand_enriched_export.json
    by (product_id, supplier_id, variation_id) — see build/export_queries.sql.
  - A new source table for the day-on-day inventory/orders series: scrap.roce_eqn__inventory_oms_dod_final,
    read via a pre-filtered scrap table (see build/export_queries.sql for why — this table is
    5.46B+ rows unfiltered and blows Presto's distributed memory limit if joined directly).
  - Two view ranges instead of one: a default 90-day window (2026-05-18 -> 2026-08-15, same
    anchor semantics as before) PLUS a lazy-loaded expanded range (2026-01-01 -> 2026-08-15) for
    the new "expand" control in index.html. Both are sliced from the SAME pulled series (anchored
    at 2026-01-01), not pulled twice.
  - The Seller ROCE rollup panel and the Dead PID x Variations panel are DROPPED entirely (no
    replacement, no approximation) — confirmed with the user 2026-08-19. There is accordingly no
    sid_roce.json and no data/dead/ output anymore.

Inputs (raw Metabase JSON exports — see build/export_queries.sql):
  roce_demand_enriched_export.json - one row per qualifying PID x SID x Variation from
                                      scrap.roce_demand_eqn__enriched (days_observed=90,
                                      instock_days>=45, order_days>=10). All 83 columns of that
                                      table, no aggregation needed (already one row per key).
  roce_demand_dod_export.json      - one row per qualifying PID x SID x Variation, with 5 packed
                                      day-on-day series (offsets/inv/dispatched/ordered/overall as
                                      CSV strings) covering 2026-01-01 through 2026-08-15 (227
                                      days), anchored at 2026-01-01. Pulled from the pre-filtered
                                      scrap table scrap.roce_demand_dod_jan_aug, not the raw
                                      5.46B-row fact table directly.

Outputs (written under OUT_DIR):
  data/index.json                - browse/search index, one row per PID x SID (aggregated across
                                    its qualifying variations), plus "rawCols" (the 83 column
                                    names, in order, that each variation's "raw" array maps to).
                                    Plain JSON, fetched once at load.
  data/shards/<p % NSHARDS>.json.gz
                                  - map "<pid>_<sid>" -> {p, s, spri, dv, vars:[...]}, one entry
                                    per variation, DEFAULT 90-day series only (2026-05-18 ->
                                    2026-08-15). Gzip-compressed; index.html decodes with
                                    DecompressionStream on fetch. Fetched for every combo shown.
  data/ext/<p % NSHARDS>.json.gz
                                  - map "<pid>_<sid>" -> {vars:[{vid, of, iv, pl, dp, ov}]} — the
                                    FULL 2026-01-01 -> 2026-08-15 series for the same combos, with
                                    no other fields (everything else is static and already in the
                                    main shard). Gzip-compressed. Fetched ONLY when the user clicks
                                    "expand" on a given combo's chart — this is what keeps the
                                    default page weight down at this ~4x-larger scope.

NSHARDS must match the constant read by index.html. NDEAD is gone (no dead panel).

Field-mapping notes (confirmed with the user 2026-08-18/19, since the new table doesn't use the
same column names as the old scrap.roce_eqn__products_classification):
  - "drr" (used for the restock heuristic threshold and browse-list DRR display) now sources from
    inventory_drr, not total_drr (that column doesn't exist in the new table).
  - "mdrr" (secondary/context DRR, not directly plotted) now sources from avg_drr_90d, not
    meesho_drr.
  - "dis" (days in stock, index-only, not directly rendered) now sources from instock_days, not
    days_in_stock (renamed in the new table).
  - is_new / meesho_demand_shape_tag / overall_demand_shape_tag / supplier_priority / slp /
    group_id / pid_created / biz_fin_category / sscat / portfolio / super_portfolio / total_orders
    / safety_stock / cycle_stock / restock_interval / dio_* / dso / odnr_frac / nbyg_frac /
    avg_inventory / min_inventory / inv_std / n_restocks — all unchanged column names, carried
    over as-is.
"""
import gzip
import json
import os
import sys
from datetime import date

IN_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "."

NSHARDS = 256

ANCHOR_MAIN = "2026-05-18"   # default 90-day view: 2026-05-18 -> 2026-08-15
ANCHOR_EXT = "2026-01-01"    # expanded view: 2026-01-01 -> 2026-08-15

# offsets in the pulled series are relative to ANCHOR_EXT (2026-01-01); this is the offset value
# of ANCHOR_MAIN (2026-05-18) within that series — entries at/after this offset are the "main"
# 90-day slice, re-based to 0 for the main shard.
CUTOFF = (date(2026, 5, 18) - date(2026, 1, 1)).days  # 137

# All 83 columns of scrap.roce_demand_eqn__enriched, in the table's natural (describe) order,
# confirmed via `describe scrap.roce_demand_eqn__enriched` on 2026-08-19. Each variation's "raw"
# array (below) holds one value per entry here, in this exact order; index.json carries this list
# once (as "rawCols") so index.html can label the values without repeating 83 keys per variation.
RAW_COLS = [
    "product_id", "supplier_id", "variation_id", "variation",
    "days_observed", "instock_days", "oos_days", "order_days",
    "avg_drr_7d", "median_drr_7d", "avg_drr_15d", "median_drr_15d", "avg_drr_30d", "median_drr_30d",
    "stddev_drr_30d", "avg_drr_60d", "median_drr_60d", "stddev_drr_60d", "avg_drr_90d",
    "median_drr_90d", "stddev_drr_90d",
    "total_orders_90d", "total_transit_stock", "odnr_perc", "inventory_drr", "meesho_drr_inv",
    "outlier_removed_inventory_drr", "outlier_removed_meesho_drr_inv",
    "avg_inventory", "min_inventory", "inv_std", "n_restocks", "safety_stock", "cycle_stock",
    "restock_interval", "dio_safety", "dio_cycle", "dio_transit", "dio_pipeline", "total_orders",
    "is_dead", "dso", "odnr_frac", "nbyg_frac",
    "first_order_date", "span_days", "max_daily_orders", "active_window_days", "zero_days",
    "early_mean", "mid_mean", "recent_mean", "early_stddev", "mid_stddev",
    "z_shift_recent_vs_mid", "z_shift_mid_vs_early", "abs_shift_recent_vs_mid",
    "abs_shift_mid_vs_early", "daily_cv",
    "overall_total_orders", "overall_max_daily_orders", "overall_zero_days",
    "overall_early_mean", "overall_mid_mean", "overall_recent_mean",
    "overall_early_stddev", "overall_mid_stddev",
    "overall_z_shift_recent_vs_mid", "overall_z_shift_mid_vs_early",
    "overall_abs_shift_recent_vs_mid", "overall_abs_shift_mid_vs_early", "overall_daily_cv",
    "meesho_demand_shape_tag", "overall_demand_shape_tag",
    "supplier_priority", "slp", "group_id", "pid_created",
    "biz_fin_category", "sscat", "portfolio", "super_portfolio", "is_new",
    # Added 2026-08-19b: the user added these 3 columns to scrap.roce_demand_eqn__enriched
    # (is_unreliable_flat_inv/suspect_inv_levels are the two component signals,
    # is_unreliable_inv = 1 if either is 1). Table now has 86 columns, not 83.
    "is_unreliable_flat_inv", "suspect_inv_levels", "is_unreliable_inv",
]


def load(name):
    path = os.path.join(IN_DIR, name)
    with open(path) as f:
        return json.load(f)


def _round_raw(v):
    if isinstance(v, float):
        return round(v, 4)
    return v


def _csv_ints(s):
    if not s:
        return []
    return [int(x) for x in s.split(",") if x != ""]


def _csv_vals(s):
    # keep as raw strings (already ints as text from the SQL cast) for re-join; only offsets need
    # int parsing for the cutoff comparison.
    if not s:
        return []
    return s.split(",")


def split_series(dod_row):
    """Split one dod-export row's Jan1-Aug15 packed series into (main_90d, ext_full) dicts of
    CSV strings, keyed the same way the shard "of/iv/pl/dp/ov" fields are."""
    offsets = _csv_ints(dod_row.get("offsets", ""))
    series = {
        "of": _csv_vals(dod_row.get("offsets", "")),
        "iv": _csv_vals(dod_row.get("inv", "")),
        "dp": _csv_vals(dod_row.get("dispatched", "")),
        "pl": _csv_vals(dod_row.get("ordered", "")),
        "ov": _csv_vals(dod_row.get("overall", "")),
    }
    n = len(offsets)
    main_idx = [i for i in range(n) if offsets[i] >= CUTOFF]

    ext = {k: ",".join(series[k]) for k in ("of", "iv", "dp", "pl", "ov")}
    main = {
        "of": ",".join(str(offsets[i] - CUTOFF) for i in main_idx),
        "iv": ",".join(series["iv"][i] for i in main_idx),
        "dp": ",".join(series["dp"][i] for i in main_idx),
        "pl": ",".join(series["pl"][i] for i in main_idx),
        "ov": ",".join(series["ov"][i] for i in main_idx),
    }
    return main, ext


def main():
    print("loading raw exports...")
    enriched_rows = load("roce_demand_enriched_export.json")
    dod_rows = load("roce_demand_dod_export.json")
    print(f"  enriched={len(enriched_rows)} dod={len(dod_rows)}")

    os.makedirs(os.path.join(OUT_DIR, "data", "shards"), exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "data", "ext"), exist_ok=True)

    dod_by_key = {}
    for r in dod_rows:
        dod_by_key[(r["product_id"], r["supplier_id"], r["variation_id"])] = r
    n_missing_series = 0

    # ---- group enriched rows by (product_id, supplier_id) ----
    combos = {}  # (p,s) -> list of variation dict
    for r in enriched_rows:
        p, s = r["product_id"], r["supplier_id"]
        combos.setdefault((p, s), []).append(r)

    shard_buckets = [dict() for _ in range(NSHARDS)]
    ext_buckets = [dict() for _ in range(NSHARDS)]
    index_rows = []

    for (p, s), vrows in combos.items():
        shard_idx = p % NSHARDS
        key = f"{p}_{s}"

        var_list = []
        ext_var_list = []
        for r in vrows:
            dod_row = dod_by_key.get((r["product_id"], r["supplier_id"], r["variation_id"]))
            if dod_row is None:
                n_missing_series += 1
                main_series = {"of": "", "iv": "", "dp": "", "pl": "", "ov": ""}
                ext_series = main_series
            else:
                main_series, ext_series = split_series(dod_row)

            var_list.append({
                "vid": r["variation_id"],
                "vn": r.get("variation"),
                "drr": r.get("inventory_drr"),
                "mdrr": r.get("avg_drr_90d"),
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
                "unrel": r.get("is_unreliable_inv"),
                "mdst": r.get("meesho_demand_shape_tag"),
                "odst": r.get("overall_demand_shape_tag"),
                "raw": [_round_raw(r.get(c)) for c in RAW_COLS],
                "of": main_series["of"],
                "iv": main_series["iv"],
                "pl": main_series["pl"],
                "dp": main_series["dp"],
                "ov": main_series["ov"],
            })
            ext_var_list.append({
                "vid": r["variation_id"],
                "of": ext_series["of"],
                "iv": ext_series["iv"],
                "pl": ext_series["pl"],
                "dp": ext_series["dp"],
                "ov": ext_series["ov"],
            })

        default_var = max(var_list, key=lambda v: (v["orders"] or 0, v["drr"] or 0))
        first = vrows[0]

        shard_buckets[shard_idx][key] = {
            "p": p, "s": s,
            "spri": first.get("supplier_priority"),
            "dv": default_var["vid"],
            "vars": var_list,
        }
        ext_buckets[shard_idx][key] = {"vars": ext_var_list}

        isnew_vals = sorted({str(r.get("is_new")) for r in vrows if r.get("is_new") is not None})
        unrel_vals = sorted({str(r.get("is_unreliable_inv")) for r in vrows if r.get("is_unreliable_inv") is not None})
        mdst_vals = sorted({r.get("meesho_demand_shape_tag") for r in vrows if r.get("meesho_demand_shape_tag")})
        odst_vals = sorted({r.get("overall_demand_shape_tag") for r in vrows if r.get("overall_demand_shape_tag")})

        index_rows.append({
            "p": p, "s": s,
            "sc": first.get("sscat"),
            "pf": first.get("portfolio"),
            "sp": first.get("super_portfolio"),
            "bf": first.get("biz_fin_category"),
            "spri": first.get("supplier_priority"),
            "drr": sum((r.get("inventory_drr") or 0) for r in vrows),
            "mdrr": sum((r.get("avg_drr_90d") or 0) for r in vrows),
            "avg": sum((r.get("avg_inventory") or 0) for r in vrows),
            "nr": sum((r.get("n_restocks") or 0) for r in vrows),
            "dis": max((r.get("instock_days") or 0) for r in vrows),
            "to": sum((r.get("total_orders") or 0) for r in vrows),
            "nv": len(vrows),
            "dv": default_var["vid"],
            "isnew": ",".join(isnew_vals),
            "unrel": ",".join(unrel_vals),
            "mdst": ",".join(mdst_vals),
            "odst": ",".join(odst_vals),
        })

    print(f"  {len(combos)} PID x SID combos, {len(enriched_rows)} variation rows")
    if n_missing_series:
        print(f"  WARNING: {n_missing_series} variations had no matching DoD series row (left blank)")

    for i, bucket in enumerate(shard_buckets):
        if not bucket:
            continue
        payload = json.dumps(bucket, separators=(",", ":")).encode("utf-8")
        with open(os.path.join(OUT_DIR, "data", "shards", f"{i}.json.gz"), "wb") as f:
            f.write(gzip.compress(payload, compresslevel=9))

    for i, bucket in enumerate(ext_buckets):
        if not bucket:
            continue
        payload = json.dumps(bucket, separators=(",", ":")).encode("utf-8")
        with open(os.path.join(OUT_DIR, "data", "ext", f"{i}.json.gz"), "wb") as f:
            f.write(gzip.compress(payload, compresslevel=9))

    cols = ["p", "s", "sc", "pf", "sp", "bf", "spri", "drr", "mdrr", "avg", "nr", "dis", "to", "nv", "dv",
            "isnew", "unrel", "mdst", "odst"]
    rows = [[r[c] for c in cols] for r in index_rows]
    index_doc = {
        "anchor": ANCHOR_MAIN,
        "extAnchor": ANCHOR_EXT,
        "nshards": NSHARDS,
        "cols": cols,
        "rows": rows,
        "rawCols": RAW_COLS,
    }
    # gzip-compressed (unlike the previous version's plain index.json) — at this scope's ~169k
    # combos the plain JSON is ~31MB, which is a meaningfully slow first load; gzip cuts that a
    # lot. index.html fetches it with the same DecompressionStream path used for shards.
    payload = json.dumps(index_doc, separators=(",", ":")).encode("utf-8")
    with open(os.path.join(OUT_DIR, "data", "index.json.gz"), "wb") as f:
        f.write(gzip.compress(payload, compresslevel=9))
    print(f"  wrote index.json.gz: {len(rows)} combos, {len(payload)} bytes raw")
    print("done.")


if __name__ == "__main__":
    main()
