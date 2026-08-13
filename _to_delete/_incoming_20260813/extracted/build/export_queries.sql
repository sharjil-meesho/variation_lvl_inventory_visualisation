-- Presto/Trino queries (Metabase "Presto Prod File Download", database id 9) used to pull the
-- three raw JSON exports that build_data.py turns into data/. Run each via Metabase's native
-- query editor, or via the /api/dataset/json fetch pattern (see HANDOFF-style notes below).
--
-- All three use array_agg(... ORDER BY log_date) to pack the 91-day series into one row per
-- PID x SID x Variation (or per dead-sample combo), instead of pulling one row per day —
-- this keeps row counts in the tens-of-thousands instead of millions, which matters because
-- scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders is 5.46 BILLION rows (26.4M PIDs) —
-- the full meesholink-supplier universe, not pre-filtered to this site's PID x Variation set.
-- A plain per-day pull for our ~72k qualifying combos alone would be ~6.4M rows; packed, it's
-- 72,397 rows. Presto handles the underlying full-table join in well under its 3-minute limit
-- (observed ~90s for the main pull, ~90s for the dead-sample pull, on 2026-08-06).
--
-- ============================================================================
-- 2026-08-13 UPDATE: base table swapped from scrap.roce_eqn__var_lvl_calcs_kri_enriched to
-- scrap.roce_eqn__products_classification (64 columns vs the old table's ~29 — same
-- product_id/supplier_id/variation_id grain, same meesho_drr>=1 & total_drr>=1 population:
-- confirmed via count query on 2026-08-13 to yield the EXACT same 72,397 rows / 50,113
-- PID×SID combos / 45,358 products / 4,754 sellers as the old table under the identical
-- filter — this is a clean drop-in replacement, not a scope change. The new table adds
-- is_new, meesho_demand_shape_tag, overall_demand_shape_tag (now used as sidebar filters —
-- see build_data.py) plus ~28 supporting demand-shape diagnostic columns (early/mid/recent
-- mean & stddev, z-shifts, daily_cv — each computed twice, once "meesho"-only and once
-- "overall") and first_order_date/span_days/group_id/category_group. All 64 columns from
-- this table are pulled and passed through to data/shards/*.json.gz as each variation's
-- "raw" array (see the "all columns" panel in index.html) — that's why the main query below
-- selects every column via arbitrary(b.col) instead of the old query's shorter explicit list.
-- The dead-sample query (query 2) was swapped to the same table too, confirmed via count
-- query to yield the identical 23,537,749-row / 11,452-seller is_dead=1 population as the
-- old table — same sample, same seller coverage.
-- ============================================================================

-- ============================================================================
-- 1. var_lvl_main_export.json — one row per qualifying PID x SID x Variation
--    (meesho_drr>=1 AND total_drr>=1). 72,397 rows as of 2026-08-13 (unchanged population
--    after the table swap above).
--
--    "overall" (overall_orders) added 2026-08-08 after the user rebuilt
--    scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders to add an inventory-drop-derived
--    order estimate: their CASE statement sets overall_orders = (live_inventory -
--    prev_inventory) only when inventory dropped day-over-day, else null — i.e. always <= 0
--    as written. We flip the sign here (-1 * a.overall_orders) so it packs as a positive
--    order count, consistent with dispatched/ordered — confirmed with the user (2026-08-08).
--
--    b's columns are all functionally dependent on (product_id, supplier_id, variation_id) —
--    there's exactly one products_classification row per that key — so arbitrary(b.col) is
--    used instead of a 64-column GROUP BY list; it just picks the (only) value deterministically.
-- ============================================================================
select
  b.product_id, b.supplier_id, b.variation_id,
  arbitrary(b.variation) as variation,
  arbitrary(b.biz_fin_category) as biz_fin_category,
  arbitrary(b.sscat) as sscat,
  arbitrary(b.portfolio) as portfolio,
  arbitrary(b.super_portfolio) as super_portfolio,
  arbitrary(b.total_drr) as total_drr,
  arbitrary(b.meesho_drr) as meesho_drr,
  arbitrary(b.days_observed) as days_observed,
  arbitrary(b.days_in_stock) as days_in_stock,
  arbitrary(b.avg_inventory) as avg_inventory,
  arbitrary(b.min_inventory) as min_inventory,
  arbitrary(b.inv_std) as inv_std,
  arbitrary(b.n_restocks) as n_restocks,
  arbitrary(b.safety_stock) as safety_stock,
  arbitrary(b.cycle_stock) as cycle_stock,
  arbitrary(b.restock_interval) as restock_interval,
  arbitrary(b.dio_safety) as dio_safety,
  arbitrary(b.dio_cycle) as dio_cycle,
  arbitrary(b.dio_transit) as dio_transit,
  arbitrary(b.dio_pipeline) as dio_pipeline,
  arbitrary(b.total_orders) as total_orders,
  arbitrary(b.is_dead) as is_dead,
  arbitrary(b.dso) as dso,
  arbitrary(b.odnr_frac) as odnr_frac,
  arbitrary(b.nbyg_frac) as nbyg_frac,
  arbitrary(b.supplier_priority) as supplier_priority,
  arbitrary(b.slp) as slp,
  arbitrary(b.group_id) as group_id,
  arbitrary(cast(b.pid_created as varchar)) as pid_created,
  arbitrary(b.category_group) as category_group,
  arbitrary(cast(b.first_order_date as varchar)) as first_order_date,
  arbitrary(b.span_days) as span_days,
  arbitrary(b.is_new) as is_new,
  arbitrary(b.max_daily_orders) as max_daily_orders,
  arbitrary(b.active_window_days) as active_window_days,
  arbitrary(b.zero_days) as zero_days,
  arbitrary(b.early_mean) as early_mean,
  arbitrary(b.mid_mean) as mid_mean,
  arbitrary(b.recent_mean) as recent_mean,
  arbitrary(b.early_stddev) as early_stddev,
  arbitrary(b.mid_stddev) as mid_stddev,
  arbitrary(b.z_shift_recent_vs_mid) as z_shift_recent_vs_mid,
  arbitrary(b.z_shift_mid_vs_early) as z_shift_mid_vs_early,
  arbitrary(b.abs_shift_recent_vs_mid) as abs_shift_recent_vs_mid,
  arbitrary(b.abs_shift_mid_vs_early) as abs_shift_mid_vs_early,
  arbitrary(b.daily_cv) as daily_cv,
  arbitrary(b.overall_total_orders) as overall_total_orders,
  arbitrary(b.overall_max_daily_orders) as overall_max_daily_orders,
  arbitrary(b.overall_zero_days) as overall_zero_days,
  arbitrary(b.overall_early_mean) as overall_early_mean,
  arbitrary(b.overall_mid_mean) as overall_mid_mean,
  arbitrary(b.overall_recent_mean) as overall_recent_mean,
  arbitrary(b.overall_early_stddev) as overall_early_stddev,
  arbitrary(b.overall_mid_stddev) as overall_mid_stddev,
  arbitrary(b.overall_z_shift_recent_vs_mid) as overall_z_shift_recent_vs_mid,
  arbitrary(b.overall_z_shift_mid_vs_early) as overall_z_shift_mid_vs_early,
  arbitrary(b.overall_abs_shift_recent_vs_mid) as overall_abs_shift_recent_vs_mid,
  arbitrary(b.overall_abs_shift_mid_vs_early) as overall_abs_shift_mid_vs_early,
  arbitrary(b.overall_daily_cv) as overall_daily_cv,
  arbitrary(b.meesho_demand_shape_tag) as meesho_demand_shape_tag,
  arbitrary(b.overall_demand_shape_tag) as overall_demand_shape_tag,
  array_join(array_agg(cast(date_diff('day', date('2026-04-01'), a.log_date) as varchar) order by a.log_date), ',') as offsets,
  array_join(array_agg(cast(coalesce(a.live_inventory,0) as varchar) order by a.log_date), ',') as inv,
  array_join(array_agg(cast(coalesce(a.dispatched_orders,0) as varchar) order by a.log_date), ',') as dispatched,
  array_join(array_agg(cast(coalesce(a.ordered_orders,0) as varchar) order by a.log_date), ',') as ordered,
  array_join(array_agg(cast(coalesce(-1*a.overall_orders,0) as varchar) order by a.log_date), ',') as overall
from scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders a
join scrap.roce_eqn__products_classification b
  on a.product_id=b.product_id and a.supplier_id=b.supplier_id and a.variation_id=b.variation_id
where a.log_date between date('2026-04-01') and date('2026-06-30')
  and b.meesho_drr >= 1 and b.total_drr >= 1
group by b.product_id, b.supplier_id, b.variation_id;

-- ============================================================================
-- 2. var_lvl_dead_export.json — deterministic 10-per-seller dead PID x Variation sample.
--    "Plottable" = avg_inventory > 0 and days_in_stock >= 5 (about half of all dead combos
--    sit at zero inventory and would chart as flat/empty lines — same product choice as the
--    original PID-level site). Sample is stable via md5-hash row_number, not rand(), so it
--    doesn't shift on re-run. 109,460 rows across 11,452 sellers as of 2026-08-06 — confirmed
--    identical (23,537,749-row / 11,452-seller pre-sample population) after the 2026-08-13
--    table swap to scrap.roce_eqn__products_classification below.
-- ============================================================================
with ranked as (
  select product_id, supplier_id, variation_id, variation, sscat, avg_inventory, days_in_stock, n_restocks, total_drr,
    row_number() over (partition by supplier_id order by md5(to_utf8(concat(cast(product_id as varchar),'_',cast(variation_id as varchar))))) as rn
  from scrap.roce_eqn__products_classification
  where is_dead = 1 and avg_inventory > 0 and days_in_stock >= 5
),
sample as (
  select * from ranked where rn <= 10
)
select
  s.product_id, s.supplier_id, s.variation_id, s.variation, s.sscat, s.avg_inventory, s.days_in_stock, s.n_restocks, s.total_drr,
  array_join(array_agg(cast(date_diff('day', date('2026-04-01'), a.log_date) as varchar) order by a.log_date), ',') as offsets,
  array_join(array_agg(cast(coalesce(a.live_inventory,0) as varchar) order by a.log_date), ',') as inv
from scrap.roce_eqn__inventory_logs_apr_jun_oms_w_orders a
join sample s on a.product_id=s.product_id and a.supplier_id=s.supplier_id and a.variation_id=s.variation_id
where a.log_date between date('2026-04-01') and date('2026-06-30')
group by s.product_id, s.supplier_id, s.variation_id, s.variation, s.sscat, s.avg_inventory, s.days_in_stock, s.n_restocks, s.total_drr;

-- ============================================================================
-- 3. var_lvl_rollup_export.json — seller-level ROCE rollup, straight passthrough.
--    Only 2 ROCE variants exist in this table (unlike the old PID-level site's 5):
--    overall (all is_dead=0 combos) and reliable_w_restock_filter (is_dead=0 AND n_restocks>=1,
--    NOT additionally filtered to avg_inventory<=15000 the way the old "reliable"/"worf"
--    variants were). 7,937 rows. Unaffected by the 2026-08-13 table swap above — this query
--    still sources scrap.roce_eqn_var_sid_lvl_rollup_roce_kri, which the user didn't ask to
--    change.
-- ============================================================================
select supplier_id,
  reliable_roce_w_restock_filter_dio_cycle, reliable_roce_w_restock_filter_dio_transit,
  reliable_roce_w_restock_filter_dio_safety, reliable_roce_w_restock_filter_dso, reliable_roce_w_restock_filter,
  overall_roce_dio_cycle, overall_roce_dio_transit, overall_roce_dio_safety, overall_roce_dso, overall_roce
from scrap.roce_eqn_var_sid_lvl_rollup_roce_kri;

-- ============================================================================
-- Pull mechanics: run each query in Metabase's native SQL editor (Presto Prod File Download,
-- database id 9), then use the browser JS console (or Claude in Chrome's javascript_tool) to
-- call the same query through the JSON API and download the result as gzip directly, e.g.:
--
--   const res = await fetch('/api/dataset/json', {
--     method: 'POST',
--     headers: {'content-type': 'application/x-www-form-urlencoded'},
--     body: new URLSearchParams({query: JSON.stringify({database: 9, type: 'native', native: {query: SQL}})})
--   });
--   const text = await res.text();  // one row per line of JSON array — no ~16,600-row UI cap
--                                    -- hit here; tested up to 100k+ rows in one call.
--
-- gzip client-side (CompressionStream) before triggering the download, then run
-- build/build_data.py against the three decompressed JSON files.
-- ============================================================================
