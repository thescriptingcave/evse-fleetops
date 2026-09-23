-- ============================================================
-- EVSE FleetOps — Beginner SQL Queries
-- Keyspace: fleetops._default.<collection>
-- Run in: http://localhost:8091 > Query > Query Editor
-- ============================================================


-- ── TIME-SERIES ──────────────────────────────────────────────

-- 1a. The last 10 readings from one station
--     ts is ISO 8601 — Couchbase sorts it correctly as a string.
SELECT ts, station_id, load_kw, temperature_c, status
FROM `fleetops`.`_default`.`telemetry`
WHERE station_id = 'EVSE-000'
ORDER BY ts DESC
LIMIT 10;


-- 1b. All readings in the last hour
--     NOW_MILLIS() returns current epoch ms; subtract 3 600 000 for 1 hour.
SELECT ts, station_id, load_kw, status
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= MILLIS_TO_STR(NOW_MILLIS() - 3600000)
ORDER BY ts DESC;


-- 1c. Count readings per station
SELECT station_id,
       COUNT(*) AS reading_count,
       MIN(ts)  AS first_reading,
       MAX(ts)  AS last_reading
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id
ORDER BY reading_count DESC;


-- ── CTEs ─────────────────────────────────────────────────────

-- 2a. Your first CTE — stations currently faulted
--     Without CTE:
SELECT serial, name, status
FROM `fleetops`.`_default`.`stations`
WHERE status = 'FAULTED';

--     The same query using a CTE (sets the pattern):
WITH faulted AS (
    SELECT serial, name, status
    FROM `fleetops`.`_default`.`stations`
    WHERE status = 'FAULTED'
)
SELECT * FROM faulted;


-- 2b. CTE to name a filter — high-priority open work orders
WITH open_high AS (
    SELECT id, station_id, title, assignee, created_ts
    FROM `fleetops`.`_default`.`workorders`
    WHERE status IN ('OPEN', 'IN_PROGRESS')
      AND priority IN ('HIGH', 'CRITICAL')
)
SELECT *
FROM open_high
ORDER BY created_ts;


-- ── WINDOW FUNCTIONS ─────────────────────────────────────────

-- 3a. Rank stations by meter reading (total energy accumulated)
--     RANK()       leaves gaps after ties: 1, 2, 2, 4
--     DENSE_RANK() does not:              1, 2, 2, 3
SELECT serial,
       name,
       status,
       meter_kwh,
       RANK()       OVER (ORDER BY meter_kwh DESC) AS energy_rank,
       DENSE_RANK() OVER (ORDER BY meter_kwh DESC) AS energy_dense_rank
FROM `fleetops`.`_default`.`stations`
ORDER BY energy_rank;


-- 3b. Number each work order per technician
--     PARTITION BY restarts the counter for each technician.
SELECT assignee,
       id,
       title,
       priority,
       created_ts,
       ROW_NUMBER() OVER (
           PARTITION BY assignee
           ORDER BY created_ts
       ) AS order_number_for_technician
FROM `fleetops`.`_default`.`workorders`
WHERE assignee IS NOT NULL
ORDER BY assignee, order_number_for_technician;


-- 3c. Running total of energy delivered per station
--     Subtracts the first meter reading so the counter starts at 0.
SELECT station_id,
       ts,
       meter_kwh,
       meter_kwh - FIRST_VALUE(meter_kwh) OVER (
           PARTITION BY station_id
           ORDER BY ts
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS energy_since_start_kwh
FROM `fleetops`.`_default`.`telemetry`
WHERE station_id = 'EVSE-000'
ORDER BY ts;
