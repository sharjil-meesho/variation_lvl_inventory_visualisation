# Inventory Explorer — Variation Level

A static, client-side site (`index.html` + `data/`, no backend) to explore Meesho inventory
by **PID × SID**, with a **variation drill-down**. This is the 2026-08-19 refresh of the site —
same core interaction model as before (look up or browse a PID×SID, pick a variation, see its
day-on-day chart and ROCE breakdown), but a new source table, a wider default+expandable date
range, and two panels dropped.

Data window: **2026-05-18 → 2026-08-15** by default (anchor `2026-05-18`, 90 days), with an
**"Expand to Jan 1 – Aug 15"** control on the chart that lazy-loads the fuller
`2026-01-01 → 2026-08-15` series for the same combo on demand.

## What changed in this refresh

- **New source table for per-variation metrics**: `scrap.roce_demand_eqn__enriched` (83 columns),
  replacing `scrap.roce_eqn__products_classification`. Scope is now `days_observed = 90 AND
  instock_days >= 45 AND order_days >= 10` — **no DRR floor**, unlike the previous
  `meesho_drr>=1 AND total_drr>=1` filter. This is a materially different (larger) population —
  see "Scope" below.
- **New source table for the day-on-day series**: `scrap.roce_eqn__inventory_oms_dod_final`,
  replacing `scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders`. This table is NOT pre-filtered
  to any SKU scope (5.78B+ rows for the 90-day window alone) — see `build/export_queries.sql` for
  why a scrap table had to be materialized first, and why direct Presto joins against it fail.
- **Wider window + a new expand control**: the default view is still a 90-day window, but it's
  now `2026-05-18 → 2026-08-15` (previously `2026-04-01 → 2026-06-30`). A new toggle next to the
  order-overlay toggle lets you expand the same chart to `2026-01-01 → 2026-08-15` — that series
  is lazy-loaded (`data/ext/`) only when you click it, so the default page weight doesn't carry
  it for every combo whether you look at it or not.
- **Two panels removed, not replaced**: the **Seller-level ROCE rollup** panel and the **Dead PID
  × Variations sample** panel are both gone. Confirmed with the user (2026-08-19) — there's no
  approximation standing in for either; if you need seller-level ROCE or a dead-SKU sample again,
  that's new scope, not a bug.
- **Field renames** (the new enriched table doesn't use the old table's column names): the "DRR"
  shown throughout the page (browse list, variation dropdown, restock-heuristic threshold) is now
  `inventory_drr`, not `total_drr`. The secondary/context DRR carried in the index is now
  `avg_drr_90d`, not `meesho_drr`. "Days in stock" now sources from `instock_days`, not
  `days_in_stock`. Everything else (`safety_stock`, `cycle_stock`, `dio_*`, `dso`, `odnr_frac`,
  `nbyg_frac`, `is_new`, `meesho_demand_shape_tag`, `overall_demand_shape_tag`, `supplier_priority`,
  `slp`, `sscat`, `portfolio`, `super_portfolio`, `biz_fin_category`) is unchanged.

## What's on the page

1. **Look up a PID × SID** or **browse & search** (sidebar) — filters on supplier priority,
   super portfolio, portfolio, sub-category (sscat), is new, Meesho demand shape, and overall
   demand shape; search by PID or SID substring. The three demand-shape-family filters are set
   *per variation*, not per PID×SID (see "Scope"), so each matches a combo if **any** of its
   variations qualify — the sidebar hint text shows the actual disagreement rate for this scope,
   computed live from `data/index.json.gz` rather than a hardcoded figure.
2. **Day-on-day inventory** — a **Variation** dropdown appears once a PID×SID is selected
   (defaults to the variation with the most orders), alongside pills for supplier priority,
   sub-category, biz-fin category, SLP, is new, Meesho demand shape, and overall demand shape for
   the selected variation. The chart is [Plotly.js](https://plotly.com/javascript/) (CDN-loaded)
   with a real calendar x-axis, drag/scroll zoom, and a hover tooltip. Reference lines for safety
   stock, avg inventory, order-up-to (est., a heuristic = safety + 2×cycle stock), and min
   inventory are overlaid, with restock markers. An **"Overlay orders (DoD)"** toggle (None /
   Placed / Dispatched / Overall) draws the chosen order series on a secondary axis. A new
   **"Date range" toggle** ("Last 90 days" / "Expand to Jan 1 – Aug 15") switches the same chart
   between the default series and the lazy-loaded full-history series — the reference lines
   (safety stock etc.) don't change with range, only the plotted series and x-axis do. "Overall
   orders" is **not** a logged order event — see "Known limitations" below.
3. **ROCE breakdown** — DIO (safety + cycle + transit) + DSO for the *selected variation only*,
   sourced from `scrap.roce_demand_eqn__enriched`.
4. **All columns (raw)** — every one of the 83 columns in `scrap.roce_demand_eqn__enriched` for
   the *selected variation*, as a plain key/value grid, including columns shown elsewhere on the
   page — a literal "everything the table has" dump, not a curated subset. Numbers are rounded to
   4 decimal places for display only.

## Scope

Base table swapped 2026-08-19 to `scrap.roce_demand_eqn__enriched`. Filter:

```sql
days_observed = 90 and instock_days >= 45 and order_days >= 10
```

No DRR floor, no supplier restriction. Actual pulled population (2026-08-19):
**284,020 PID×SID×Variation rows / 169,325 PID×SID combos / 6,525 sellers** — roughly 4x the
previous scope's combo count, since the old `meesho_drr>=1 AND total_drr>=1` filter is gone. (An
earlier count query on 2026-08-18 estimated 166,398 combos / 6,399 sellers — the small difference
from the actual pulled numbers above is unremarkable at this scale and not worth re-chasing.)

`is_new` / `meesho_demand_shape_tag` / `overall_demand_shape_tag` are still set **per variation,
not per product**; the sidebar's disagreement-rate hint is computed live from the actual data at
page load (see `updateDisagreeHint()` in `index.html`) rather than a hardcoded percentage, since
that rate is specific to each scope/table and would otherwise silently go stale on a refresh like
this one.

`meesho_demand_shape_tag` and `overall_demand_shape_tag` each take one of 8 values: `smooth`,
`gradual_decrease`, `gradual_increase`, `step_up`, `sudden_drop`, `up_down_bau_volatile`,
`no_baseline`, `spike_and_drop`.

## File layout

```
index.html                 the app — fetches data/* over http(s), won't work from file://
data/index.json.gz         browse/search index: one row per PID×SID (aggregated across its
                            qualifying variations) + "rawCols" (the 83 column-name labels for
                            each variation's "raw" array) + "anchor"/"extAnchor". Gzip-compressed
                            (unlike the previous version's plain index.json) — at this scope's
                            ~169k combos the plain JSON is ~31MB, gzip cuts that a lot.
data/shards/<p%256>.json.gz  per-PID×SID×Variation records + the default 90-day series + all 83
                            raw scrap-table columns, gzip-compressed
data/ext/<p%256>.json.gz   per-PID×SID×Variation records with ONLY the full 2026-01-01 ->
                            2026-08-15 series (of/iv/pl/dp/ov) — no static fields, since those
                            don't change with range. Fetched lazily, only when a user clicks
                            "expand" on a given combo's chart.
build/build_data.py         turns the 2 raw warehouse JSON exports into data/
build/export_queries.sql    the exact Presto/Trino queries used to pull those 2 exports, plus the
                            Spark SQL scrap-table CREATE that had to run first (see that file for
                            why — the raw DoD fact table is too large to join directly in Presto)
README.md                   this file
```

Local check: `python3 -m http.server 8000` from this directory, then open
`http://localhost:8000`. Needs a browser with `DecompressionStream` support (all current
Chrome/Edge/Firefox/Safari) since the shard and ext files are gzip-compressed and decoded
client-side.

**Data size**: this scope is ~4x the previous one by combo count, and now carries 83 raw columns
per variation (vs 64 before) plus a second (lazy-loaded) series tree. Watch `data/` total size
before pushing — this repo previously hit an HTTP 408 on `git push` through the corporate proxy
at ~36MB uncompressed; the *previous* refresh landed around ~55MB and needed staged commits. If
`git push` fails: push over a direct connection if available, split `data/shards/` (and now
`data/ext/`) into a few commits, or ask about Git LFS (note LFS doesn't actually serve correctly
via GitHub Pages, per this repo's own history — staged commits are the more reliable fix).

## Refresh recipe

1. Re-run the two queries in `build/export_queries.sql` (Metabase, Presto Prod File Download,
   database id 9) — each in 16 chunks (`product_id % 16`), per the notes in that file. If the
   `scrap.roce_demand_dod_jan_aug` scrap table needs rebuilding first (e.g. scope or window
   changed), run the `CREATE TABLE` statement documented at the top of that file via the Inhouse
   Notebook Spark-SQL kernel first — confirm with the user before running it, it's a write.
2. Concatenate each query's 16 chunks into one JSON array and save as
   `roce_demand_enriched_export.json` and `roce_demand_dod_export.json` in one folder.
3. `python3 build/build_data.py <folder-with-the-2-jsons> .` (run from the repo root) —
   regenerates `data/index.json.gz`, `data/shards/*.json.gz`, `data/ext/*.json.gz`.

`NSHARDS` (256) is a constant in both `build_data.py` and `index.html` — keep them in sync if you
change it. `CUTOFF` in `build_data.py` (137 — the offset of 2026-05-18 within the
2026-01-01-anchored pulled series) must be recomputed if either anchor date changes.

## Known limitations / heuristics (call these out, don't hide them)

- **Restock detection** on the day-on-day chart is a client-side heuristic — a day-over-day
  inventory jump ≥ `max(5, 2×that variation's inventory_drr, 10% of that day's post-jump
  inventory)` — not a logged restock event.
- **"order-up-to (est)" reference line** is `safety stock + 2×cycle stock`, a heuristic — not a
  warehouse-computed target level. This and the other reference lines (safety stock, avg
  inventory, min inventory) don't change when you expand the date range — they're computed once
  per variation from `scrap.roce_demand_eqn__enriched`, not per day.
- **"Overall orders" overlay** is an inventory-drop-derived estimate (day-over-day inventory
  decrease, sign flipped positive), not a logged order event the way "Placed orders" and
  "Dispatched orders" are. It's only as good as the underlying `overall_orders` logic in
  `scrap.roce_eqn__inventory_oms_dod_final` — a day where inventory drops for any reason
  (write-off, correction, etc.), not just a sale, would show up here too.
- **Chart requires Plotly.js from a CDN** (cdnjs, falling back to jsdelivr then unpkg). If all
  three are unreachable, the day-on-day chart shows a "failed to load" message instead of
  silently breaking; everything else on the page still works.
- **"DRR" now means inventory_drr, not total_drr/meesho_drr** — see "What changed" above. This is
  a confirmed field-mapping decision, not an oversight; the all-columns panel below the chart
  shows `avg_drr_90d` and the other order-count DRR variants (`avg_drr_7d/15d/30d/60d`,
  `median_drr_*`, `outlier_removed_*`) alongside it for comparison.
- **`is_new` / demand-shape tags are per variation, not per product** — the sidebar shows the
  live disagreement rate for this scope (see "Scope"). The pills next to the variation dropdown
  show only the *currently selected* variation's values, so a combo can pass a filter for a
  reason the visible pill doesn't show if a different variation is the one that qualifies.
- **No Seller-level ROCE panel, no Dead PID × Variations panel** — both dropped in this refresh
  (see "What changed"), not hidden gaps.
- **The "All columns" panel is intentionally redundant** with the ROCE breakdown and pills above
  it (same source table, same variation) — it's a literal raw dump by request, not a
  deduplicated view.
