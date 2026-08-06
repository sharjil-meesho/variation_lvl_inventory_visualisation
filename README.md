# Inventory Explorer — Variation Level

A static, client-side site (`index.html` + `data/`, no backend) to explore Meesho inventory
by **PID × SID**, with a **variation drill-down**. Sibling to the PID×SID-level
[`inventory_visualisation`](https://github.com/sharjil-meesho/inventory_visualisation) site —
same sidebar/browse model, same three stacked panels below the chart — but every PID×SID can
now have multiple variations (color/size/etc.), and you pick which one's day-on-day chart and
ROCE breakdown to look at.

Data window: **2026-04-01 → 2026-06-30** (anchor `2026-04-01`), same as the PID-level site.

## What's on the page

1. **Look up a PID × SID** or **browse & search** (sidebar, unchanged in spirit from the
   PID-level site) — filters on supplier priority, super portfolio, portfolio, sub-category
   (sscat); search by PID or SID substring.
2. **Day-on-day inventory** — a **Variation** dropdown appears once a PID×SID is selected
   (defaults to the variation with the most orders). The chart, restock markers, and safety/cycle
   reference lines all update to the selected variation.
3. **ROCE breakdown** — DIO (safety + cycle + transit) + DSO for the *selected variation only*,
   sourced directly from `scrap.roce_eqn__var_lvl_calcs_kri_enriched`. Unlike the PID-level site,
   ODNR fraction and NMV/GMV fraction are real here (not stuck at 0) — the source table has them.
4. **Seller-level ROCE (all PID × Variations)** — order-weighted rollup across everything that
   seller has, from `scrap.roce_eqn_var_sid_lvl_rollup_roce_kri`. Only **2 variants** are
   available here (Overall, Reliable/restock-filtered) — the old PID-level site had 5
   (it also tracked "dead FG" separately); this rollup table doesn't compute those, so the
   dropdown only offers what the table actually has.
5. **Dead PID × Variations — random sample** — same idea as the PID-level site's dead panel,
   now at PID×Variation grain. Deterministic sample of up to 10 per seller.

## Scope

Built from `select * from scrap.roce_eqn__var_lvl_calcs_kri where meesho_drr >= 1 and
total_drr >= 1` — 72,397 PID×SID×Variation rows across 50,113 PID×SID pairs and 4,754 sellers,
as of 2026-08-06. To widen scope later (e.g. drop the DRR floor, or include more sellers),
re-run the query in `build/export_queries.sql` with a different `WHERE` and rebuild — nothing
else in the pipeline assumes this specific filter.

## File layout

```
index.html                 the app — fetches data/* over http(s), won't work from file://
data/index.json            browse/search index: one row per PID×SID (aggregated across its
                            qualifying variations), plain JSON
data/shards/<p%256>.json.gz   per-PID×SID×Variation records + series, gzip-compressed
data/sid_roce.json         seller ROCE rollup (2 variants), plain JSON
data/dead/<s%64>.json.gz   dead PID×Variation sample per seller, gzip-compressed
build/build_data.py        turns the 3 raw warehouse JSON exports into data/
build/export_queries.sql   the exact Presto/Trino queries used to pull those 3 exports,
                            plus notes on how the packed array_agg approach avoids paging
                            through the underlying 5.46-billion-row inventory log table
README.md                  this file
```

Local check: `python3 -m http.server 8000` from this directory, then open
`http://localhost:8000`. Needs a browser with `DecompressionStream` support (all current
Chrome/Edge/Firefox/Safari) since the shard and dead files are gzip-compressed and decoded
client-side — this keeps the repo to ~38MB instead of ~164MB uncompressed, which matters
for `git push` through a corporate proxy (the PID-level site hit an HTTP 408 at ~36MB
uncompressed; see its own HANDOFF.md for that story).

## Refresh recipe

1. Re-run the 3 queries in `build/export_queries.sql` (Metabase, Presto Prod File Download,
   database id 9) — or point them at a wider `WHERE` clause if expanding scope.
2. Save the 3 results as `var_lvl_main_export.json`, `var_lvl_dead_export.json`,
   `var_lvl_rollup_export.json` in one folder.
3. `python3 build/build_data.py <folder-with-the-3-jsons> .` (run from the repo root) —
   regenerates `data/index.json`, `data/shards/*.json.gz`, `data/sid_roce.json`,
   `data/dead/*.json.gz`.

`NSHARDS` (256) and `NDEAD` (64) are constants in both `build_data.py` and `index.html` —
keep them in sync if you change either.

## Known limitations / heuristics (call these out, don't hide them)

- **Restock detection** on the day-on-day chart is a client-side heuristic — a day-over-day
  inventory jump ≥ `max(5, 2×that variation's total_drr, 10% of the prior day's inventory)` —
  not a logged restock event. Same formula the PID-level site used.
- **"dead ~Xd" in the dead-sample dropdown** is `avg_inventory ÷ that variation's own total_drr`,
  a rough order-of-magnitude proxy, not the warehouse-computed `avg_dead_fg` metric the
  PID-level site had (that used a category-level DRR reference and isn't available in the
  tables this site is built from). Shown as "n/a" when total_drr is ~0.
- **Seller-level "Reliable" variant** here is `is_dead=0 AND n_restocks>=1`, order-weighted —
  it does **not** additionally restrict to `avg_inventory<=15000` the way the old PID-level
  site's "reliable"/"worf" variants did. That's simply what
  `scrap.roce_eqn_var_sid_lvl_rollup_roce_kri` computes; if you want the 15k-filtered variant
  back, it needs a new rollup query against `var_lvl_calcs_kri_enriched`.
