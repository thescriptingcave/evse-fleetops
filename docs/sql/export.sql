-- ============================================================
-- EVSE FleetOps — Export / Reporting Queries
-- Keyspace: fleetops._default.<collection>
-- Run in: http://localhost:8091 > Query > Query Editor
--
-- These queries produce flat, wide result sets suitable for
-- CSV export, BI tools, or scheduled reports.
-- ============================================================


-- ── TIME-SERIES EXPORTS ──────────────────────────────────────

-- 1j. Daily telemetry summary — one row per station per day
--     Covers load, energy, temperature, and status breakdown.
SELECT station_id,
       DATE_TRUNC_STR(ts, 'day')                        AS date,
       COUNT(*)                                          AS total_readings,
       ROUND(AVG(load_kw), 2)                           AS avg_load_kw,
       ROUND(MAX(load_kw), 2)                           AS peak_load_kw,
       ROUND(MAX(meter_kwh) - MIN(meter_kwh), 3)        AS energy_kwh,
       ROUND(AVG(temperature_c), 1)                     AS avg_temp_c,
       ROUND(MAX(temperature_c), 1)                     AS max_temp_c,
       SUM(CASE WHEN status = 'CHARGING'
                THEN 1 ELSE 0 END)                      AS charging_samples,
       SUM(CASE WHEN status = 'FAULTED'
                THEN 1 ELSE 0 END)                      AS faulted_samples
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_TRUNC_STR(ts, 'day')
ORDER BY date DESC, station_id;


-- 1k. Hourly load heatmap — one row per station per hour of day (0–23)
--     Useful for building heatmap charts in BI tools.
SELECT station_id,
       DATE_PART_STR(ts, 'hour')  AS hour_of_day,
       ROUND(AVG(load_kw), 2)     AS avg_load_kw,
       COUNT(*)                    AS samples
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_PART_STR(ts, 'hour')
ORDER BY station_id, hour_of_day;


-- ── CTE EXPORTS ──────────────────────────────────────────────

-- 2i. Monthly operations report — telemetry + sessions joined by month
WITH monthly_telemetry AS (
    SELECT station_id,
           DATE_TRUNC_STR(ts, 'month')              AS month,
           ROUND(AVG(load_kw), 2)                   AS avg_load_kw,
           ROUND(MAX(load_kw), 2)                   AS peak_load_kw,
           ROUND(MAX(meter_kwh) - MIN(meter_kwh), 2) AS energy_kwh,
           SUM(CASE WHEN status = 'FAULTED'
                    THEN 1 ELSE 0 END)              AS fault_samples,
           COUNT(*)                                  AS total_samples
    FROM `fleetops`.`_default`.`telemetry`
    GROUP BY station_id, DATE_TRUNC_STR(ts, 'month')
),
monthly_sessions AS (
    SELECT station_id,
           DATE_TRUNC_STR(start_ts, 'month')        AS month,
           COUNT(*)                                  AS total_sessions,
           ROUND(SUM(kwh_delivered), 2)              AS total_kwh,
           ROUND(AVG(kwh_delivered), 2)              AS avg_kwh_per_session
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED'
    GROUP BY station_id, DATE_TRUNC_STR(start_ts, 'month')
)
SELECT t.station_id,
       t.month,
       t.avg_load_kw,
       t.peak_load_kw,
       t.energy_kwh                                           AS telemetry_energy_kwh,
       s.total_sessions,
       s.total_kwh                                            AS session_energy_kwh,
       s.avg_kwh_per_session,
       ROUND(t.fault_samples * 100.0
             / NULLIF(t.total_samples, 0), 2)                AS fault_pct
FROM monthly_telemetry t
LEFT JOIN monthly_sessions s
       ON t.station_id = s.station_id AND t.month = s.month
ORDER BY t.month DESC, t.station_id;


-- ── WINDOW FUNCTION EXPORTS ──────────────────────────────────

-- 3j. Station performance scorecard — one row per station, all KPIs
--     Combines telemetry, sessions and work orders with an energy rank.
WITH telemetry_stats AS (
    SELECT station_id,
           COUNT(*)                                              AS total_readings,
           ROUND(AVG(load_kw), 2)                               AS avg_load_kw,
           ROUND(MAX(load_kw), 2)                               AS peak_load_kw,
           ROUND(AVG(temperature_c), 1)                         AS avg_temp_c,
           SUM(CASE WHEN status = 'FAULTED' THEN 1 ELSE 0 END) AS fault_count
    FROM `fleetops`.`_default`.`telemetry`
    GROUP BY station_id
),
session_stats AS (
    SELECT station_id,
           COUNT(*)                                             AS total_sessions,
           ROUND(SUM(kwh_delivered), 2)                        AS total_kwh,
           ROUND(AVG(kwh_delivered), 2)                        AS avg_kwh_per_session,
           ROUND(AVG(DATE_DIFF_STR(
               end_ts, start_ts, 'minute')), 0)                AS avg_session_min
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED' AND end_ts IS NOT NULL
    GROUP BY station_id
),
work_stats AS (
    SELECT station_id,
           COUNT(*)                                              AS total_work_orders,
           SUM(CASE WHEN status IN ('OPEN','IN_PROGRESS')
                    THEN 1 ELSE 0 END)                          AS open_orders,
           SUM(CASE WHEN priority = 'CRITICAL'
                    THEN 1 ELSE 0 END)                          AS critical_orders
    FROM `fleetops`.`_default`.`workorders`
    GROUP BY station_id
)
SELECT s.serial,
       s.name,
       s.site_type,
       s.model,
       s.status,
       -- Telemetry KPIs
       t.avg_load_kw,
       t.peak_load_kw,
       t.avg_temp_c,
       ROUND(t.fault_count * 100.0
             / NULLIF(t.total_readings, 0), 2)                 AS fault_rate_pct,
       -- Session KPIs
       ss.total_sessions,
       ss.total_kwh,
       ss.avg_kwh_per_session,
       ss.avg_session_min,
       -- Work order KPIs
       COALESCE(w.total_work_orders, 0)                        AS total_work_orders,
       COALESCE(w.open_orders, 0)                              AS open_work_orders,
       COALESCE(w.critical_orders, 0)                          AS critical_work_orders,
       -- Fleet ranking
       RANK() OVER (ORDER BY COALESCE(ss.total_kwh, 0) DESC)  AS energy_rank
FROM `fleetops`.`_default`.`stations` s
LEFT JOIN telemetry_stats t  ON s.serial = t.station_id
LEFT JOIN session_stats  ss  ON s.serial = ss.station_id
LEFT JOIN work_stats      w  ON s.serial = w.station_id
ORDER BY energy_rank;


-- 3k. Work order aging report — open orders ranked by how long they've waited
SELECT id,
       title,
       priority,
       status,
       assignee,
       station_id,
       created_ts,
       ROUND(DATE_DIFF_STR(NOW_STR(), created_ts, 'hour'), 0)  AS age_hours,
       RANK() OVER (
           PARTITION BY priority
           ORDER BY DATE_DIFF_STR(NOW_STR(), created_ts, 'hour') DESC
       ) AS age_rank_within_priority,
       ROUND(
           AVG(DATE_DIFF_STR(NOW_STR(), created_ts, 'hour'))
           OVER (PARTITION BY priority),
       0) AS avg_age_hours_for_priority
FROM `fleetops`.`_default`.`workorders`
WHERE status IN ('OPEN', 'IN_PROGRESS')
ORDER BY priority, age_rank_within_priority;
