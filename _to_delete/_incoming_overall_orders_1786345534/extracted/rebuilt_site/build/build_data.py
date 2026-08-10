#!/usr/bin/env python3
"""
Build the data/ directory for the variation-level ROCE inventory explorer.

Inputs (raw Metabase JSON exports, produced via the packed array_agg queries):
  var_lvl_main_export.json   - 72,397 rows: one per qualifying PID x SID x Variation
                                (meesho_drr>=1 AND total_drr>=1), each with a packed
                                day-on-day series (offsets/inv/dispatched/ordered/overall as
                                CSV strings — "overall" = inventory-drop-derived order count,
                                added 2026-08-08, sign already flipped positive in the SQL).
  var_lvl_dead_export.json   - 109,460 rows: deterministic 10-per-seller dead PID x Variation
                                sample (is_dead=1, avg_inventory>0, days_in_stock>=5), each with
                                a packed live-inventory series.
  var_lvl_rollup_export.json - 7,937 rows: seller-level ROCE rollup (2 variants: overall,
                                reliable_w_restock_filter).

Outputs (written under OUT_DIR):
  data/index.json               - browse/search index, one row per PID x SID (aggregated across
                                   its qualifying variations). Plain JSON, fetched once at load.
  data/shards/<p % NSHARDS>.json.gz
                                 - map "<pid>_<sid>" -> {p, s, dv, vars:[...]}, one entry per
                                   variation. Gzip-compressed; index.html decodes with
                                   DecompressionStream on fetch (cuts ~99MB to ~26MB).
  data/sid_roce.json            - map "<sid>" -> [10 values] (2 ROCE variants x 5 fields each).
                                   Plain JSON, fetched once at load.
  data/dead/<s % NDEAD>.json.gz - map "<sid>" -> [ [pid, vid, vn, sscat, avg, dis, nr, drr, of, iv], ... ]
                                  Gzip-compressed (cuts ~63MB to ~3.5MB).

NSHARDS / NDEAD must match the constants read by index.html.
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


def load(name):
    path = os.path.join(IN_DIR, name)
    with open(path) as f:
        return json.load(f)


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
    cols = ["p", "s", "sc", "pf", "sp", "bf", "spri", "drr", "mdrr", "avg", "nr", "dis", "to", "nv", "dv"]
    rows = [[r[c] for c in cols] for r in index_rows]
    index_doc = {
        "anchor": ANCHOR,
        "nshards": NSHARDS,
        "cols": cols,
        "rows": rows,
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
