-- ============================================================
-- EVSE FleetOps — Intermediate SQL Queries
-- Keyspace: fleetops._default.<collection>
-- Run in: http://localhost:8091 > Query > Query Editor
-- ============================================================


-- ── TIME-SERIES ──────────────────────────────────────────────

-- 1d. Hourly average load per station (last 24 hours)
--     DATE_TRUNC_STR rounds a timestamp down to the given unit.
--     Change 'hour' to 'minute', 'day', 'week', or 'month'.
SELECT station_id,
       DATE_TRUNC_STR(ts, 'hour')   AS hour_bucket,
       ROUND(AVG(load_kw), 2)       AS avg_load_kw,
       ROUND(MAX(load_kw), 2)       AS peak_load_kw,
       COUNT(*)                      AS sample_count
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= DATE_ADD_STR(NOW_STR(), -24, 'hour')
GROUP BY station_id, DATE_TRUNC_STR(ts, 'hour')
ORDER BY station_id, hour_bucket;


-- 1e. Energy delivered per day (meter delta method)
--     The meter accumulates total kWh; daily energy = MAX - MIN per day.
SELECT station_id,
       DATE_TRUNC_STR(ts, 'day')                 AS day,
       ROUND(MAX(meter_kwh) - MIN(meter_kwh), 3) AS energy_delivered_kwh,
       COUNT(*)                                   AS readings
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_TRUNC_STR(ts, 'day')
HAVING MAX(meter_kwh) > MIN(meter_kwh)
ORDER BY day DESC, energy_delivered_kwh DESC;


-- 1f. Time spent in each status per station today
--     Uses a window SUM inside GROUP BY to get the per-station total
--     so we can compute the percentage without a self-join.
SELECT station_id,
       status,
       COUNT(*) AS sample_count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY station_id), 1)
           AS pct_of_day
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= DATE_TRUNC_STR(NOW_STR(), 'day')
GROUP BY station_id, status
ORDER BY station_id, pct_of_day DESC;


-- ── CTEs ─────────────────────────────────────────────────────

-- 2c. Two CTEs joined together — urgent work orders with station details
WITH urgent_orders AS (
    SELECT id, station_id, title, priority, status, assignee
    FROM `fleetops`.`_default`.`workorders`
    WHERE priority IN ('HIGH', 'CRITICAL')
),
station_info AS (
    SELECT serial, name, site_type, model
    FROM `fleetops`.`_default`.`stations`
)
SELECT o.id,
       o.title,
       o.priority,
       o.status,
       o.assignee,
       s.name     AS station_name,
       s.site_type
FROM urgent_orders o
JOIN station_info s ON o.station_id = s.serial
ORDER BY o.priority, o.status;


-- 2d. CTE with aggregation — technician workload summary
WITH order_counts AS (
    SELECT assignee,
           COUNT(*)                                                 AS total_orders,
           SUM(CASE WHEN status = 'OPEN'        THEN 1 ELSE 0 END) AS open_count,
           SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress_count,
           SUM(CASE WHEN status = 'RESOLVED'    THEN 1 ELSE 0 END) AS resolved_count,
           SUM(CASE WHEN priority = 'CRITICAL'  THEN 1 ELSE 0 END) AS critical_count
    FROM `fleetops`.`_default`.`workorders`
    WHERE assignee IS NOT NULL
    GROUP BY assignee
)
SELECT *,
       ROUND(resolved_count * 100.0 / NULLIF(total_orders, 0), 1) AS resolution_rate_pct
FROM order_counts
ORDER BY total_orders DESC;


-- 2e. Chained CTEs — fleet health score by site type
--     Each CTE builds on the one above it.
WITH station_status AS (
    SELECT serial, name, site_type, status, last_seen
    FROM `fleetops`.`_default`.`stations`
),
status_scores AS (
    SELECT serial,
           name,
           site_type,
           status,
           CASE status
               WHEN 'AVAILABLE'   THEN 100
               WHEN 'CHARGING'    THEN 100
               WHEN 'MAINTENANCE' THEN  50
               WHEN 'OFFLINE'     THEN  10
               WHEN 'FAULTED'     THEN   0
               ELSE 0
           END AS health_score
    FROM station_status
),
fleet_summary AS (
    SELECT site_type,
           COUNT(*)                               AS station_count,
           ROUND(AVG(health_score), 0)            AS avg_health_score,
           SUM(CASE WHEN health_score = 100
                    THEN 1 ELSE 0 END)            AS fully_operational
    FROM status_scores
    GROUP BY site_type
)
SELECT *,
       ROUND(fully_operational * 100.0 / NULLIF(station_count, 0), 0)
           AS operational_pct
FROM fleet_summary
ORDER BY avg_health_score;


-- ── WINDOW FUNCTIONS ─────────────────────────────────────────

-- 3d. Load change between consecutive readings (LAG)
--     LAG(col, 1) fetches the value from the previous row in the window.
--     LEAD(col, 1) fetches the value from the next row.
SELECT ts,
       station_id,
       load_kw,
       LAG(load_kw, 1) OVER (
           PARTITION BY station_id
           ORDER BY ts
       ) AS prev_load_kw,
       ROUND(load_kw - LAG(load_kw, 1) OVER (
           PARTITION BY station_id
           ORDER BY ts
       ), 3) AS load_delta_kw
FROM `fleetops`.`_default`.`telemetry`
WHERE station_id = 'EVSE-000'
ORDER BY ts DESC
LIMIT 20;


-- 3e. Session duration vs station average
SELECT station_id,
       id AS session_id,
       start_ts,
       end_ts,
       kwh_delivered,
       ROUND(DATE_DIFF_STR(end_ts, start_ts, 'minute'), 0)     AS duration_min,
       ROUND(AVG(DATE_DIFF_STR(end_ts, start_ts, 'minute'))
             OVER (PARTITION BY station_id), 0)                 AS avg_duration_min,
       ROUND(DATE_DIFF_STR(end_ts, start_ts, 'minute')
             - AVG(DATE_DIFF_STR(end_ts, start_ts, 'minute'))
               OVER (PARTITION BY station_id), 0)               AS diff_from_avg_min
FROM `fleetops`.`_default`.`sessions`
WHERE state = 'COMPLETED'
  AND end_ts IS NOT NULL
ORDER BY station_id, start_ts;


-- 3f. Each station's share of total fleet energy
--     OVER () with no PARTITION BY covers the entire result set —
--     useful for computing a grand total inside a GROUP BY query.
SELECT station_id,
       ROUND(SUM(kwh_delivered), 2)                    AS station_kwh,
       ROUND(SUM(SUM(kwh_delivered)) OVER (), 2)       AS fleet_total_kwh,
       ROUND(
           SUM(kwh_delivered) * 100.0
           / SUM(SUM(kwh_delivered)) OVER (),
       2) AS pct_of_fleet
FROM `fleetops`.`_default`.`sessions`
WHERE state = 'COMPLETED'
GROUP BY station_id
ORDER BY station_kwh DESC;
