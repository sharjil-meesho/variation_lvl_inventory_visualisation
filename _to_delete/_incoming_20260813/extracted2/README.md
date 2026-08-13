# Inventory Explorer — Variation Level

A static, client-side site (`index.html` + `data/`, no backend) to explore Meesho inventory
by **PID × SID**, with a **variation drill-down**. Sibling to the PID×SID-level
[`inventory_visualisation`](https://github.com/sharjil-meesho/inventory_visualisation) site —
same sidebar/browse model, same three stacked panels below the chart — but every PID×SID can
now have multiple variations (color/size/etc.), and you pick which one's day-on-day chart and
ROCE breakdown to look at.

Data window: **2026-04-01 → 2026-06-30** (anchor `2026-04-01`), same as the PID-level site.

## What's on the page

1. **Look up a PID × SID** or **browse & search** (sidebar) — filters on supplier priority,
   super portfolio, portfolio, sub-category (sscat), and (added 2026-08-13) **is new**,
   **Meesho demand shape**, and **overall demand shape**; search by PID or SID substring. The
   3 new filters are set *per variation*, not per PID×SID — see "Scope" below — so each matches
   a combo if **any** of its variations qualify.
2. **Day-on-day inventory** — a **Variation** dropdown appears once a PID×SID is selected
   (defaults to the variation with the most orders), alongside pills for supplier priority,
   sub-category (sscat), biz-fin category, SLP, and (added 2026-08-13) **is new** / **Meesho
   demand shape** / **overall demand shape** for the selected variation (the first three pills
   are PID×SID-level, from `data/index.json`; the rest are per-variation and update when you
   switch variations). The chart is a [Plotly.js](https://plotly.com/javascript/)
   line chart (loaded from a CDN, same as the PID-level site) with a real calendar x-axis,
   drag-to-zoom / scroll-to-zoom, and a hover tooltip showing the day's inventory and its
   day-over-day delta. Reference lines for safety stock, avg inventory, order-up-to (est.,
   a heuristic = safety + 2×cycle stock — not a warehouse field), and min inventory are
   overlaid, along with restock markers (diamonds). An **"Overlay orders (DoD)"** toggle
   (None / Placed orders / Dispatched orders / Overall orders) draws the chosen order series
   as a filled area on a secondary right-hand axis, on the same chart as live inventory — not
   a separate panel. "Overall orders" (added 2026-08-08) is **not** a logged order event like
   the other two — it's an inventory-drop-derived estimate: day-over-day inventory decrease,
   from the user's own rebuilt `overall_orders` column (sign flipped positive on export; see
   `build/export_queries.sql`). Everything updates to the selected variation.
3. **ROCE breakdown** — DIO (safety + cycle + transit) + DSO for the *selected variation only*,
   sourced directly from `scrap.roce_eqn__products_classification` (see "Scope" below for the
   2026-08-13 table swap). Unlike the PID-level site, ODNR fraction and NMV/GMV fraction are
   real here (not stuck at 0) — the source table has them.
4. **All columns (raw)** — added 2026-08-13, sits directly below the ROCE breakdown and above
   the seller-level ROCE panel. Every one of the 64 columns in
   `scrap.roce_eqn__products_classification` for the *selected variation*, shown as a plain
   key/value grid — including columns already shown elsewhere on the page (supplier priority,
   sscat, safety stock, etc.), by design (a literal "everything the scrap table has" dump, not
   a curated subset). Numbers are rounded to 4 decimal places for display only. Mostly useful
   for the ~28 demand-shape diagnostic columns (`early_mean`/`mid_mean`/`recent_mean`,
   `*_stddev`, `z_shift_*`, `abs_shift_*`, `daily_cv` — each computed twice, once "meesho"-only
   and once "overall") that feed `meesho_demand_shape_tag` / `overall_demand_shape_tag` but
   aren't otherwise surfaced, plus `is_dead`, `first_order_date`, `span_days`, `group_id`,
   `category_group`, and `pid_created`.
5. **Seller-level ROCE (all PID × Variations)** — order-weighted rollup across everything that
   seller has, from `scrap.roce_eqn_var_sid_lvl_rollup_roce_kri`. Only **2 variants** are
   available here (Overall, Reliable/restock-filtered) — the old PID-level site had 5
   (it also tracked "dead FG" separately); this rollup table doesn't compute those, so the
   dropdown only offers what the table actually has.
6. **Dead PID × Variations — random sample** — same idea as the PID-level site's dead panel,
   now at PID×Variation grain. Deterministic sample of up to 10 per seller.

## Scope

**Base table swapped 2026-08-13** from `scrap.roce_eqn__var_lvl_calcs_kri_enriched` to
`scrap.roce_eqn__products_classification` — a 64-column superset at the same
product_id/supplier_id/variation_id grain, adding `is_new`, `meesho_demand_shape_tag`,
`overall_demand_shape_tag` (now filters/pills — see above) plus ~28 supporting demand-shape
diagnostic columns and `first_order_date`/`span_days`/`group_id`/`category_group`. Confirmed via
count query that `select * from scrap.roce_eqn__products_classification where total_drr >= 1
and meesho_drr >= 1` yields the **exact same** population as the old table under the identical
filter — 72,397 PID×SID×Variation rows across 50,113 PID×SID pairs, 45,358 distinct products,
and 4,754 distinct sellers, as of 2026-08-13 — so this was a clean drop-in replacement, not a
scope change. The dead-sample query (`build/export_queries.sql`, query 2) was swapped to the
same table for consistency, also confirmed identical (23,537,749-row / 11,452-seller
`is_dead=1` pre-sample population, matching the old table exactly).

`is_new` / `meesho_demand_shape_tag` / `overall_demand_shape_tag` are set **per variation, not
per product**: 5,305 of 50,113 combos (~10.6%) have variations that disagree on at least one of
the three (e.g. one variation is `smooth`, another is `step_up`). The 3 sidebar filters match a
combo if **any** of its variations have the selected value — same "any variation qualifies"
pattern as the `dead_basis` filter on the sibling `roce_inventory_var_lvl_new_dead` site. See
`build_data.py`'s `"isnew"`/`"mdst"`/`"odst"` index fields (comma-joined unique values per
combo) and `index.html`'s filter logic.

`meesho_demand_shape_tag` and `overall_demand_shape_tag` each take one of 8 values: `smooth`,
`gradual_decrease`, `gradual_increase`, `step_up`, `sudden_drop`, `up_down_bau_volatile`,
`no_baseline`, `spike_and_drop`.

To widen scope later (e.g. drop the DRR floor, or include more sellers), re-run the query in
`build/export_queries.sql` with a different `WHERE` and rebuild — nothing else in the pipeline
assumes this specific filter.

Re-pulled 2026-08-08 (same scope/row counts) to add the "overall" packed field, sourced from
the user's rebuilt `scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders` (now has
`prev_inventory` and `overall_orders` columns).

## File layout

```
index.html                 the app — fetches data/* over http(s), won't work from file://
data/index.json            browse/search index: one row per PID×SID (aggregated across its
                            qualifying variations) + "rawCols" (the 64 column-name labels for
                            each variation's "raw" array), plain JSON
data/shards/<p%256>.json.gz   per-PID×SID×Variation records + series + all 64 raw scrap-table
                            columns, gzip-compressed
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
client-side.

**⚠️ Data size grew substantially on 2026-08-13.** Adding all 64 `scrap.roce_eqn__products_classification`
columns per variation (per explicit request, to keep this a literal "everything the table has"
dump rather than a curated subset) pushed `data/` from ~30MB to **~55MB** even after rounding
stored floats to 4 decimal places (`build_data.py`'s `_round_raw`) — `data/shards/*.json.gz`
alone is ~41MB, up from ~26MB. This repo previously hit an HTTP 408 on `git push` through the
corporate proxy at ~36MB uncompressed (see git history / HANDOFF notes); at ~55MB there is a
real chance the same thing happens again. If `git push` fails: try pushing over a direct
connection (bypassing the proxy) if available, split the push into multiple commits (e.g.
commit `data/shards/` in a few batches), or ask about Git LFS for the `data/` directory. If you'd
rather shrink the payload instead of fighting the proxy, the fix is in `build_data.py`'s
`RAW_COLS` list — trim it to the columns you actually look at (the ~28 demand-shape diagnostic
columns are the bulk of the size) and rebuild.

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
  inventory jump ≥ `max(5, 2×that variation's total_drr, 10% of that day's post-jump inventory)` —
  not a logged restock event. Same formula the PID-level site used.
- **"order-up-to (est)" reference line** is `safety stock + 2×cycle stock`, the same heuristic
  the PID-level site plots — not a warehouse-computed target level.
- **"Overall orders" overlay** is an inventory-drop-derived estimate (day-over-day inventory
  decrease, sign flipped positive), not a logged order event the way "Placed orders" and
  "Dispatched orders" are. It's only as good as the underlying `overall_orders` CASE logic in
  `scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders` — a day where inventory drops for any
  reason (write-off, correction, etc.), not just a sale, would show up here too.
- **Chart requires Plotly.js from a CDN** (cdnjs, falling back to jsdelivr then unpkg) — same
  dependency the PID-level site has. If all three are unreachable (fully offline, or a network
  policy blocks all three), the day-on-day chart shows a "failed to load" message instead of
  silently breaking; everything else on the page still works.
- **"dead ~Xd" in the dead-sample dropdown** is `avg_inventory ÷ that variation's own total_drr`,
  a rough order-of-magnitude proxy, not the warehouse-computed `avg_dead_fg` metric the
  PID-level site had (that used a category-level DRR reference and isn't available in the
  tables this site is built from). Shown as "n/a" when total_drr is ~0.
- **Seller-level "Reliable" variant** here is `is_dead=0 AND n_restocks>=1`, order-weighted —
  it does **not** additionally restrict to `avg_inventory<=15000` the way the old PID-level
  site's "reliable"/"worf" variants did. That's simply what
  `scrap.roce_eqn_var_sid_lvl_rollup_roce_kri` computes; if you want the 15k-filtered variant
  back, it needs a new rollup query against `var_lvl_calcs_kri_enriched`.
- **`is_new` / demand-shape tags are per variation, not per product** — ~10.6% of combos have
  disagreeing variations. The sidebar filters use "any variation qualifies" logic (see
  "Scope"); the pills next to the variation dropdown show only the *currently selected*
  variation's values, so a combo can pass a filter for a reason the visible pill doesn't show
  (if a different variation is the one that actually qualifies). Switch variations to check.
- **The "All columns" panel is intentionally redundant** with the ROCE breakdown and pills
  above it (same source table, same variation) — it's a literal raw dump by request, not a
  deduplicated view. See the size/git-push note under "File layout" above if this repo becomes
  hard to push.
