-- ============================================================
-- EVSE FleetOps — Advanced SQL Queries
-- Keyspace: fleetops._default.<collection>
-- Run in: http://localhost:8091 > Query > Query Editor
-- ============================================================


-- ── TIME-SERIES ──────────────────────────────────────────────

-- 1g. Temperature anomaly detection — z-score > 2 standard deviations
--     Computes per-station mean and stddev in a CTE, then flags outliers.
WITH station_stats AS (
    SELECT station_id,
           AVG(temperature_c)    AS avg_temp,
           STDDEV(temperature_c) AS stddev_temp
    FROM `fleetops`.`_default`.`telemetry`
    WHERE temperature_c IS NOT NULL
    GROUP BY station_id
)
SELECT t.ts,
       t.station_id,
       ROUND(t.temperature_c, 1)                           AS temp_c,
       ROUND(s.avg_temp, 1)                                 AS avg_temp_c,
       ROUND((t.temperature_c - s.avg_temp)
             / NULLIF(s.stddev_temp, 0), 2)                AS z_score
FROM `fleetops`.`_default`.`telemetry` t
JOIN station_stats s ON t.station_id = s.station_id
WHERE t.temperature_c IS NOT NULL
  AND ABS((t.temperature_c - s.avg_temp)
          / NULLIF(s.stddev_temp, 0)) > 2
ORDER BY ABS((t.temperature_c - s.avg_temp)
             / NULLIF(s.stddev_temp, 0)) DESC
LIMIT 50;


-- 1h. 5-minute rolling average load (sliding RANGE window)
--     ts_ms (epoch milliseconds) is used so the RANGE can be expressed
--     as a numeric distance. 300 000 ms = 5 minutes.
SELECT ts,
       station_id,
       load_kw,
       AVG(load_kw) OVER (
           PARTITION BY station_id
           ORDER BY ts_ms
           RANGE BETWEEN 300000 PRECEDING AND CURRENT ROW
       ) AS rolling_5min_avg_kw
FROM `fleetops`.`_default`.`telemetry`
WHERE station_id = 'EVSE-000'
  AND ts >= DATE_ADD_STR(NOW_STR(), -1, 'hour')
ORDER BY ts;


-- 1i. Gap detection — periods where a station stopped reporting (> 2 min)
WITH ordered AS (
    SELECT station_id,
           ts,
           ts_ms,
           LEAD(ts_ms) OVER (
               PARTITION BY station_id
               ORDER BY ts_ms
           ) AS next_ts_ms
    FROM `fleetops`.`_default`.`telemetry`
),
gaps AS (
    SELECT station_id,
           ts                                          AS gap_start,
           MILLIS_TO_STR(next_ts_ms)                  AS gap_end,
           ROUND((next_ts_ms - ts_ms) / 60000.0, 1)  AS gap_minutes
    FROM ordered
    WHERE next_ts_ms - ts_ms > 120000
)
SELECT *
FROM gaps
ORDER BY gap_minutes DESC
LIMIT 20;


-- ── CTEs ─────────────────────────────────────────────────────

-- 2f. UNNEST — count notes per work order
--     UNNEST unpacks the notes array so each note becomes its own row.
WITH note_rows AS (
    SELECT wo.id,
           wo.title,
           wo.priority,
           wo.status,
           n.author,
           n.ts AS note_ts
    FROM `fleetops`.`_default`.`workorders` wo
    UNNEST wo.notes AS n
),
note_counts AS (
    SELECT id, title, priority, status,
           COUNT(*)                    AS note_count,
           MAX(note_ts)               AS last_note_ts,
           ARRAY_AGG(DISTINCT author) AS contributors
    FROM note_rows
    GROUP BY id, title, priority, status
)
SELECT *
FROM note_counts
ORDER BY note_count DESC;


-- 2g. Status transition timeline (simulate RECURSIVE with LAG)
--     Couchbase SQL++ does not support RECURSIVE CTEs.
--     LAG inside a CTE gives the previous status so we can filter to
--     only the rows where the status actually changed.
WITH ordered_telemetry AS (
    SELECT station_id,
           ts,
           status,
           LAG(status) OVER (
               PARTITION BY station_id
               ORDER BY ts
           ) AS prev_status
    FROM `fleetops`.`_default`.`telemetry`
    WHERE station_id = 'EVSE-000'
),
transitions AS (
    SELECT station_id,
           ts,
           prev_status,
           status AS new_status
    FROM ordered_telemetry
    WHERE status <> prev_status
      AND prev_status IS NOT NULL
)
SELECT *
FROM transitions
ORDER BY ts;


-- 2h. Full fleet ops report — joins all four collections
WITH latest_telemetry AS (
    SELECT station_id,
           MAX(ts)        AS last_seen,
           AVG(load_kw)   AS avg_load_kw,
           MAX(meter_kwh) AS current_meter_kwh
    FROM `fleetops`.`_default`.`telemetry`
    WHERE ts >= DATE_ADD_STR(NOW_STR(), -1, 'hour')
    GROUP BY station_id
),
session_summary AS (
    SELECT station_id,
           COUNT(*)                     AS sessions_today,
           ROUND(SUM(kwh_delivered), 2) AS kwh_today
    FROM `fleetops`.`_default`.`sessions`
    WHERE start_ts >= DATE_TRUNC_STR(NOW_STR(), 'day')
    GROUP BY station_id
),
open_orders AS (
    SELECT station_id,
           COUNT(*) AS open_work_orders
    FROM `fleetops`.`_default`.`workorders`
    WHERE status IN ('OPEN', 'IN_PROGRESS')
    GROUP BY station_id
)
SELECT s.serial,
       s.name,
       s.status,
       s.site_type,
       t.last_seen,
       ROUND(t.avg_load_kw, 2)             AS avg_load_kw,
       ss.sessions_today,
       ss.kwh_today,
       COALESCE(o.open_work_orders, 0)     AS open_work_orders
FROM `fleetops`.`_default`.`stations` s
LEFT JOIN latest_telemetry  t  ON s.serial = t.station_id
LEFT JOIN session_summary  ss  ON s.serial = ss.station_id
LEFT JOIN open_orders       o  ON s.serial = o.station_id
ORDER BY s.serial;


-- ── WINDOW FUNCTIONS ─────────────────────────────────────────

-- 3g. Top-3 peak load readings per station (per-partition Top-N)
--     ROW_NUMBER inside a CTE lets us filter to the top N after ranking.
WITH ranked AS (
    SELECT ts,
           station_id,
           load_kw,
           temperature_c,
           ROW_NUMBER() OVER (
               PARTITION BY station_id
               ORDER BY load_kw DESC
           ) AS rn
    FROM `fleetops`.`_default`.`telemetry`
    WHERE load_kw IS NOT NULL
)
SELECT ts, station_id, load_kw, temperature_c
FROM ranked
WHERE rn <= 3
ORDER BY station_id, rn;


-- 3h. Session streaks — consecutive sessions with no gap > 30 minutes
--     Step 1: find the gap between each session and the previous one.
--     Step 2: use a running SUM to assign a streak group ID
--             (the ID increments every time a gap > 30 min is found).
WITH session_gaps AS (
    SELECT station_id,
           id,
           start_ts,
           end_ts,
           kwh_delivered,
           LAG(end_ts) OVER (
               PARTITION BY station_id ORDER BY start_ts
           ) AS prev_end_ts,
           DATE_DIFF_STR(
               start_ts,
               LAG(end_ts) OVER (
                   PARTITION BY station_id ORDER BY start_ts
               ),
               'minute'
           ) AS gap_from_prev_min
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED' AND end_ts IS NOT NULL
),
streak_groups AS (
    SELECT *,
           SUM(CASE WHEN gap_from_prev_min > 30
                         OR gap_from_prev_min IS NULL
                    THEN 1 ELSE 0 END)
               OVER (PARTITION BY station_id ORDER BY start_ts
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
               AS streak_id
    FROM session_gaps
)
SELECT station_id,
       streak_id,
       COUNT(*)                      AS sessions_in_streak,
       MIN(start_ts)                 AS streak_start,
       MAX(end_ts)                   AS streak_end,
       ROUND(SUM(kwh_delivered), 2)  AS total_kwh_in_streak
FROM streak_groups
GROUP BY station_id, streak_id
HAVING COUNT(*) > 1
ORDER BY sessions_in_streak DESC;


-- 3i. NTILE percentile buckets — station energy quartiles
--     NTILE(4) divides stations into 4 equal groups by total energy.
--     Use NTILE(100) for true percentile buckets.
WITH station_energy AS (
    SELECT station_id,
           ROUND(SUM(kwh_delivered), 2) AS total_kwh
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED'
    GROUP BY station_id
),
percentiles AS (
    SELECT station_id,
           total_kwh,
           NTILE(4) OVER (ORDER BY total_kwh DESC) AS quartile
    FROM station_energy
)
SELECT station_id,
       total_kwh,
       quartile,
       CASE quartile
           WHEN 1 THEN 'Top 25%'
           WHEN 2 THEN 'Upper-mid 25%'
           WHEN 3 THEN 'Lower-mid 25%'
           WHEN 4 THEN 'Bottom 25%'
       END AS tier
FROM percentiles
ORDER BY total_kwh DESC;
