-- Presto/Trino queries (Metabase "Presto Prod File Download", database id 9) + one Spark SQL
-- scrap-table build (Inhouse Notebook kernel) used to pull the two raw JSON exports that
-- build_data.py turns into data/. This replaces the 2026-08-13 version of this file (which read
-- scrap.roce_eqn__products_classification + scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders).
--
-- ============================================================================
-- WHY A SCRAP TABLE THIS TIME (read this before re-running the pull)
-- ============================================================================
-- The new day-on-day source table, scrap.roce_eqn__inventory_oms_dod_final, is NOT pre-filtered
-- to any SKU scope the way the old apr_jun table was — it's the full catalog, every product,
-- every supplier, every day. Just the 90-day window (2026-05-18 -> 2026-08-15) is 5.78 BILLION
-- rows (28M distinct products, 12,244 suppliers); the full 2026-01-01 -> 2026-08-15 window this
-- site now needs is proportionally larger still.
--
-- Joining that directly against our ~166k-combo qualifying keyset (from
-- scrap.roce_demand_eqn__enriched) inside Metabase/Presto FAILS — even at a 500-row test scale —
-- with "Query exceeded distributed user memory limit of 150GB". A semi-join (tuple IN-subquery)
-- filter avoids the memory blowup but is still a full 5.78B+-row scan every time, which is far
-- too slow to repeat 16x for chunked pulls.
--
-- The fix: materialize a small scrap table ONCE via Spark SQL (Path B / the Inhouse Notebook
-- kernel — Metabase's Presto connection does not have SELECT permission on these tables via
-- Databricks, only via its own separate Presto/Hive-metastore grant, so the join has to happen in
-- Spark, reading the SHORT table names — no hive_metastore. prefix on reads, only on the CREATE
-- target):
--
--   CREATE TABLE hive_metastore.scrap.roce_demand_dod_jan_aug AS
--   SELECT a.product_id, a.supplier_id, a.variation_id, a.log_date, a.live_inventory,
--          a.dispatched_orders, a.ordered_orders, a.overall_orders
--   FROM scrap.roce_eqn__inventory_oms_dod_final a
--   JOIN (
--     SELECT product_id, supplier_id, variation_id
--     FROM scrap.roce_demand_eqn__enriched
--     WHERE days_observed = 90 AND instock_days >= 45 AND order_days >= 10
--   ) b
--   ON a.product_id = b.product_id AND a.supplier_id = b.supplier_id AND a.variation_id = b.variation_id
--   WHERE a.log_date >= date('2026-01-01') AND a.log_date <= date('2026-08-15');
--
-- Confirmed with the user before running (2026-08-19) — this is a write (CREATE TABLE) to the
-- warehouse. Took ~80s to build. Result: 57,990,021 rows / 161,572 distinct products, exactly
-- 2026-01-01 -> 2026-08-15 as requested. All subsequent reads of the DoD series go through this
-- scrap table (short name scrap.roce_demand_dod_jan_aug), which Metabase/Presto handles fine —
-- it's ~58M rows, not billions.
--
-- If this table ever needs a full refresh, re-run the CREATE above (DROP TABLE IF EXISTS first,
-- or CREATE OR REPLACE TABLE, confirming with the user either way — see the
-- meesho-warehouse-browser-sql skill's safety rules on writes).
-- ============================================================================

-- ============================================================================
-- 1. roce_demand_enriched_export.json — one row per qualifying PID x SID x Variation from
--    scrap.roce_demand_eqn__enriched. 284,020 rows / 169,325 PID x SID combos / 6,525 sellers
--    (actual pulled numbers, 2026-08-19) — no DRR floor, no supplier restriction; scope is
--    entirely defined by this WHERE clause. All columns of the table, straight SELECT (no
--    GROUP BY needed — one row per key already). Below is the original 83-column pull; as of
--    2026-08-19b the table has 3 more columns (is_unreliable_flat_inv, suspect_inv_levels,
--    is_unreliable_inv) — see query 3 below for how those were added without re-pulling
--    everything. A from-scratch re-run of this query should just add those 3 columns to this
--    SELECT list directly instead of doing a separate supplemental pull.
--
--    Pulled in 16 chunks (product_id % 16 = 0..15) purely to keep each Metabase response small
--    (full unchunked pull is ~650MB of raw JSON text) — chunk, don't re-filter the population.
-- ============================================================================
select
  product_id, supplier_id, variation_id, variation,
  days_observed, instock_days, oos_days, order_days,
  avg_drr_7d, median_drr_7d, avg_drr_15d, median_drr_15d, avg_drr_30d, median_drr_30d, stddev_drr_30d,
  avg_drr_60d, median_drr_60d, stddev_drr_60d, avg_drr_90d, median_drr_90d, stddev_drr_90d,
  total_orders_90d, total_transit_stock, odnr_perc, inventory_drr, meesho_drr_inv,
  outlier_removed_inventory_drr, outlier_removed_meesho_drr_inv,
  avg_inventory, min_inventory, inv_std, n_restocks, safety_stock, cycle_stock, restock_interval,
  dio_safety, dio_cycle, dio_transit, dio_pipeline, total_orders, is_dead, dso, odnr_frac, nbyg_frac,
  cast(first_order_date as varchar) as first_order_date, span_days, max_daily_orders, active_window_days, zero_days,
  early_mean, mid_mean, recent_mean, early_stddev, mid_stddev, z_shift_recent_vs_mid, z_shift_mid_vs_early,
  abs_shift_recent_vs_mid, abs_shift_mid_vs_early, daily_cv,
  overall_total_orders, overall_max_daily_orders, overall_zero_days, overall_early_mean, overall_mid_mean, overall_recent_mean,
  overall_early_stddev, overall_mid_stddev, overall_z_shift_recent_vs_mid, overall_z_shift_mid_vs_early,
  overall_abs_shift_recent_vs_mid, overall_abs_shift_mid_vs_early, overall_daily_cv,
  meesho_demand_shape_tag, overall_demand_shape_tag,
  supplier_priority, slp, group_id, cast(pid_created as varchar) as pid_created,
  biz_fin_category, sscat, portfolio, super_portfolio, is_new,
  is_unreliable_flat_inv, suspect_inv_levels, is_unreliable_inv   -- added 2026-08-19b
from scrap.roce_demand_eqn__enriched
where days_observed = 90 and instock_days >= 45 and order_days >= 10
  and product_id % 16 = <k>;   -- run for k = 0..15, concatenate the 16 JSON arrays into one file

-- ============================================================================
-- 2. roce_demand_dod_export.json — one row per qualifying PID x SID x Variation, with 5 packed
--    day-on-day series covering the FULL 2026-01-01 -> 2026-08-15 range (227 days), anchored at
--    2026-01-01 (offset 0 = 2026-01-01). build_data.py slices this into the default 90-day shard
--    series (offset >= 137, i.e. 2026-05-18 onward, re-based to 0) and the full-range "ext"
--    series (used only when the user clicks "expand" on the chart) from the SAME pulled row —
--    this is pulled ONCE per scope, not twice.
--
--    "overall" is sign-flipped (-1 * overall_orders) for the same reason as every prior version
--    of this site: the source column is (live_inventory - prev_inventory) only on a day
--    inventory *dropped*, i.e. always <= 0 as stored.
--
--    Reads from the pre-filtered scrap table (see the "why a scrap table" note above) — NOT
--    directly from scrap.roce_eqn__inventory_oms_dod_final.
-- ============================================================================
select
  product_id, supplier_id, variation_id,
  array_join(array_agg(cast(date_diff('day', date('2026-01-01'), log_date) as varchar) order by log_date), ',') as offsets,
  array_join(array_agg(cast(coalesce(live_inventory,0) as varchar) order by log_date), ',') as inv,
  array_join(array_agg(cast(coalesce(dispatched_orders,0) as varchar) order by log_date), ',') as dispatched,
  array_join(array_agg(cast(coalesce(ordered_orders,0) as varchar) order by log_date), ',') as ordered,
  array_join(array_agg(cast(coalesce(-1*overall_orders,0) as varchar) order by log_date), ',') as overall
from scrap.roce_demand_dod_jan_aug
where product_id % 16 = <k>   -- run for k = 0..15, concatenate the 16 JSON arrays into one file
group by product_id, supplier_id, variation_id;

-- ============================================================================
-- 3. ric_supplement.json (2026-08-19b) — supplemental pull, NOT part of the original refresh.
--    The user added 3 columns to scrap.roce_demand_eqn__enriched after the initial pull above:
--    is_unreliable_flat_inv, suspect_inv_levels, is_unreliable_inv (= 1 if either of the first two
--    is 1). Rather than re-pulling all 83 original columns again, this is a narrow supplemental
--    pull of just the new columns for the SAME population (same WHERE clause, same 284,020 rows),
--    merged onto roce_demand_enriched_export.json by (product_id, supplier_id, variation_id) —
--    see build_data.py's RAW_COLS (now 86 entries) and the "unrel" field on each variation.
--
--    Small enough (6 narrow columns x 284,020 rows, ~39MB raw JSON) to pull in one shot, no
--    chunking needed (took ~8s).
--
--    New filter added to the site from this: "Reliable inventory curve" (Yes/No), Yes when
--    is_unreliable_inv = 0. Same per-variation "any variation qualifies" semantics as the
--    existing is_new / demand-shape filters.
-- ============================================================================
select
  product_id, supplier_id, variation_id,
  is_unreliable_flat_inv, suspect_inv_levels, is_unreliable_inv
from scrap.roce_demand_eqn__enriched
where days_observed = 90 and instock_days >= 45 and order_days >= 10;

-- ============================================================================
-- Removed from this version (confirmed with the user 2026-08-19 — dropped, not replaced):
--   - The seller-level ROCE rollup query (previously read scrap.roce_eqn_var_sid_lvl_rollup_roce_kri)
--     — no analogue pulled, no sid_roce.json output, no Seller ROCE panel in index.html.
--   - The dead PID x Variation sample query — no dead-sample pull, no data/dead/ output, no Dead
--     panel in index.html.
-- ============================================================================

-- ============================================================================
-- Pull mechanics: both queries above were run in 16 chunks each (product_id % 16), inside the
-- browser via Claude-in-Chrome's javascript_tool hitting Metabase's JSON API directly —
--
--   const res = await fetch('/api/dataset/json', {
--     method: 'POST',
--     headers: {'content-type': 'application/x-www-form-urlencoded'},
--     body: new URLSearchParams({query: JSON.stringify({database: 9, type: 'native', native: {query: SQL}})})
--   });
--   const text = await res.text();
--
-- — chunking purely to keep each response small (~40MB/chunk instead of one ~650MB / ~500MB
-- response), NOT because any single chunk query is close to Metabase's 3-minute runtime limit.
-- Chunks were concatenated into one JSON array per query, gzip-compressed (CompressionStream),
-- and downloaded via a Blob + anchor "download" trigger, then staged into the build environment
-- through the device file bridge — same mechanics as the previous version of this file.
-- ============================================================================
