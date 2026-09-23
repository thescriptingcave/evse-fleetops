# SQL Tutorials — EVSE FleetOps Database

Hands-on SQL++ (Couchbase's SQL dialect, a superset of standard SQL) using the
real EVSE FleetOps collections: `stations`, `telemetry`, `sessions`, and
`workorders`. Every query runs against the local Couchbase instance.

**How to run queries:**
Open the Couchbase Web Console at `http://localhost:8091`, go to
**Query → Query Editor**, and paste any query below. Or use the REST API:

```bash
curl -s -u Administrator:password \
  http://localhost:8093/query/service \
  -d 'statement=SELECT "hello" AS test'
```

**Keyspace format:** `fleetops`.`_default`.`<collection>`

---

## Part 1 — Time-Series SQL

Telemetry is the heartbeat of the fleet. Every EVSE station pushes a reading
roughly once per second: load, temperature, meter reading, and status.

### Beginner

**1a. The last 10 readings from one station**

```sql
SELECT ts, station_id, load_kw, temperature_c, status
FROM `fleetops`.`_default`.`telemetry`
WHERE station_id = 'EVSE-000'
ORDER BY ts DESC
LIMIT 10;
```

> `ts` is an ISO 8601 string (`2026-09-23T18:37:19.000Z`). Couchbase sorts
> strings lexicographically, which works correctly for ISO 8601.

---

**1b. All readings in the last hour**

```sql
SELECT ts, station_id, load_kw, status
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= MILLIS_TO_STR(NOW_MILLIS() - 3600000)
ORDER BY ts DESC;
```

> `NOW_MILLIS()` returns the current epoch time in milliseconds.
> Subtracting `3600000` (1 hour) gives one hour ago.

---

**1c. Count readings per station**

```sql
SELECT station_id,
       COUNT(*) AS reading_count,
       MIN(ts)  AS first_reading,
       MAX(ts)  AS last_reading
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id
ORDER BY reading_count DESC;
```

---

### Intermediate

**1d. Hourly average load per station**

Bucketing by hour is the foundation of time-series dashboards.

```sql
SELECT station_id,
       DATE_TRUNC_STR(ts, 'hour')   AS hour_bucket,
       ROUND(AVG(load_kw), 2)       AS avg_load_kw,
       ROUND(MAX(load_kw), 2)       AS peak_load_kw,
       COUNT(*)                      AS sample_count
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= DATE_ADD_STR(NOW_STR(), -24, 'hour')
GROUP BY station_id, DATE_TRUNC_STR(ts, 'hour')
ORDER BY station_id, hour_bucket;
```

> `DATE_TRUNC_STR(ts, 'hour')` rounds the timestamp down to the hour.
> Change `'hour'` to `'minute'`, `'day'`, `'week'`, or `'month'`.

---

**1e. Energy delivered per day (from meter delta)**

The meter accumulates total kWh. Daily energy = end reading − start reading.

```sql
SELECT station_id,
       DATE_TRUNC_STR(ts, 'day')                              AS day,
       ROUND(MAX(meter_kwh) - MIN(meter_kwh), 3)              AS energy_delivered_kwh,
       COUNT(*)                                                AS readings
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_TRUNC_STR(ts, 'day')
HAVING MAX(meter_kwh) > MIN(meter_kwh)
ORDER BY day DESC, energy_delivered_kwh DESC;
```

---

**1f. Time spent in each status per station today**

```sql
SELECT station_id,
       status,
       COUNT(*) AS sample_count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY station_id), 1)
           AS pct_of_day
FROM `fleetops`.`_default`.`telemetry`
WHERE ts >= DATE_TRUNC_STR(NOW_STR(), 'day')
GROUP BY station_id, status
ORDER BY station_id, pct_of_day DESC;
```

---

### Advanced

**1g. Temperature anomaly detection — readings 2 standard deviations above average**

```sql
WITH station_stats AS (
    SELECT station_id,
           AVG(temperature_c)                        AS avg_temp,
           STDDEV(temperature_c)                     AS stddev_temp
    FROM `fleetops`.`_default`.`telemetry`
    WHERE temperature_c IS NOT NULL
    GROUP BY station_id
)
SELECT t.ts,
       t.station_id,
       ROUND(t.temperature_c, 1)                     AS temp_c,
       ROUND(s.avg_temp, 1)                           AS avg_temp_c,
       ROUND((t.temperature_c - s.avg_temp)
             / NULLIF(s.stddev_temp, 0), 2)          AS z_score
FROM `fleetops`.`_default`.`telemetry` t
JOIN station_stats s ON t.station_id = s.station_id
WHERE t.temperature_c IS NOT NULL
  AND ABS((t.temperature_c - s.avg_temp)
          / NULLIF(s.stddev_temp, 0)) > 2
ORDER BY ABS((t.temperature_c - s.avg_temp)
             / NULLIF(s.stddev_temp, 0)) DESC
LIMIT 50;
```

---

**1h. 5-minute rolling average load (sliding window)**

```sql
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
```

> `ts_ms` (epoch milliseconds) is used in the `RANGE` clause because the
> window frame is measured in numeric distance, not string order.
> `300000` = 5 minutes in milliseconds.

---

**1i. Gap detection — find periods where a station stopped reporting**

```sql
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
           ts                                             AS gap_start,
           MILLIS_TO_STR(next_ts_ms)                     AS gap_end,
           ROUND((next_ts_ms - ts_ms) / 60000.0, 1)     AS gap_minutes
    FROM ordered
    WHERE next_ts_ms - ts_ms > 120000   -- gaps longer than 2 minutes
)
SELECT *
FROM gaps
ORDER BY gap_minutes DESC
LIMIT 20;
```

---

### Export Queries

**1j. Daily telemetry summary — ready for CSV export**

```sql
SELECT station_id,
       DATE_TRUNC_STR(ts, 'day')           AS date,
       COUNT(*)                             AS total_readings,
       ROUND(AVG(load_kw), 2)              AS avg_load_kw,
       ROUND(MAX(load_kw), 2)              AS peak_load_kw,
       ROUND(MAX(meter_kwh)
             - MIN(meter_kwh), 3)          AS energy_kwh,
       ROUND(AVG(temperature_c), 1)        AS avg_temp_c,
       ROUND(MAX(temperature_c), 1)        AS max_temp_c,
       SUM(CASE WHEN status = 'CHARGING'
                THEN 1 ELSE 0 END)         AS charging_samples,
       SUM(CASE WHEN status = 'FAULTED'
                THEN 1 ELSE 0 END)         AS faulted_samples
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_TRUNC_STR(ts, 'day')
ORDER BY date DESC, station_id;
```

---

**1k. Hourly load heatmap — one row per station per hour of day (0–23)**

```sql
SELECT station_id,
       DATE_PART_STR(ts, 'hour')       AS hour_of_day,
       ROUND(AVG(load_kw), 2)          AS avg_load_kw,
       COUNT(*)                         AS samples
FROM `fleetops`.`_default`.`telemetry`
GROUP BY station_id, DATE_PART_STR(ts, 'hour')
ORDER BY station_id, hour_of_day;
```

---

## Part 2 — Common Table Expressions (CTEs)

A CTE (`WITH` clause) names a subquery so you can reference it like a table.
It makes complex queries readable and avoids repeating the same subquery twice.

### Beginner

**2a. Your first CTE — stations currently faulted**

Without CTE:
```sql
SELECT serial, name, status
FROM `fleetops`.`_default`.`stations`
WHERE status = 'FAULTED';
```

The same thing with a CTE — no functional difference, but sets the pattern:
```sql
WITH faulted AS (
    SELECT serial, name, status
    FROM `fleetops`.`_default`.`stations`
    WHERE status = 'FAULTED'
)
SELECT * FROM faulted;
```

---

**2b. CTE to simplify a WHERE clause — high-priority open work orders**

```sql
WITH open_high AS (
    SELECT id, station_id, title, assignee, created_ts
    FROM `fleetops`.`_default`.`workorders`
    WHERE status IN ('OPEN', 'IN_PROGRESS')
      AND priority IN ('HIGH', 'CRITICAL')
)
SELECT *
FROM open_high
ORDER BY created_ts;
```

---

### Intermediate

**2c. Two CTEs — join station info onto work orders**

```sql
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
       s.name   AS station_name,
       s.site_type
FROM urgent_orders o
JOIN station_info s ON o.station_id = s.serial
ORDER BY o.priority, o.status;
```

---

**2d. CTE with aggregation — technician workload summary**

```sql
WITH order_counts AS (
    SELECT assignee,
           COUNT(*)                                            AS total_orders,
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
```

---

**2e. Chained CTEs — fleet health score**

Each CTE builds on the previous one.

```sql
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
               WHEN 'MAINTENANCE' THEN 50
               WHEN 'OFFLINE'     THEN 10
               WHEN 'FAULTED'     THEN 0
               ELSE 0
           END AS health_score
    FROM station_status
),
fleet_summary AS (
    SELECT site_type,
           COUNT(*)                          AS station_count,
           ROUND(AVG(health_score), 0)       AS avg_health_score,
           SUM(CASE WHEN health_score = 100
                    THEN 1 ELSE 0 END)       AS fully_operational
    FROM status_scores
    GROUP BY site_type
)
SELECT *,
       ROUND(fully_operational * 100.0 / NULLIF(station_count, 0), 0)
           AS operational_pct
FROM fleet_summary
ORDER BY avg_health_score;
```

---

### Advanced

**2f. CTE with unnesting — count notes per work order**

Work order notes are stored as an array inside each document. `UNNEST` unpacks
the array into rows.

```sql
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
           COUNT(*) AS note_count,
           MAX(note_ts) AS last_note_ts,
           ARRAY_AGG(DISTINCT author) AS contributors
    FROM note_rows
    GROUP BY id, title, priority, status
)
SELECT *
FROM note_counts
ORDER BY note_count DESC;
```

---

**2g. Recursive-style CTE — station timeline (status transitions)**

Couchbase SQL++ does not support `RECURSIVE` CTEs but you can simulate a
transition report by comparing consecutive telemetry rows with window functions
inside a CTE:

```sql
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
```

---

**2h. Multi-CTE fleet ops report — combines telemetry, sessions and work orders**

```sql
WITH latest_telemetry AS (
    SELECT station_id,
           MAX(ts)         AS last_seen,
           AVG(load_kw)    AS avg_load_kw,
           MAX(meter_kwh)  AS current_meter_kwh
    FROM `fleetops`.`_default`.`telemetry`
    WHERE ts >= DATE_ADD_STR(NOW_STR(), -1, 'hour')
    GROUP BY station_id
),
session_summary AS (
    SELECT station_id,
           COUNT(*)                              AS sessions_today,
           ROUND(SUM(kwh_delivered), 2)          AS kwh_today
    FROM `fleetops`.`_default`.`sessions`
    WHERE start_ts >= DATE_TRUNC_STR(NOW_STR(), 'day')
    GROUP BY station_id
),
open_orders AS (
    SELECT station_id,
           COUNT(*)  AS open_work_orders
    FROM `fleetops`.`_default`.`workorders`
    WHERE status IN ('OPEN', 'IN_PROGRESS')
    GROUP BY station_id
)
SELECT s.serial,
       s.name,
       s.status,
       s.site_type,
       t.last_seen,
       ROUND(t.avg_load_kw, 2)      AS avg_load_kw,
       ss.sessions_today,
       ss.kwh_today,
       COALESCE(o.open_work_orders, 0) AS open_work_orders
FROM `fleetops`.`_default`.`stations` s
LEFT JOIN latest_telemetry  t  ON s.serial = t.station_id
LEFT JOIN session_summary   ss ON s.serial = ss.station_id
LEFT JOIN open_orders       o  ON s.serial = o.station_id
ORDER BY s.serial;
```

---

### Export Queries

**2i. CTE-based monthly ops report**

```sql
WITH monthly_telemetry AS (
    SELECT station_id,
           DATE_TRUNC_STR(ts, 'month')    AS month,
           ROUND(AVG(load_kw), 2)         AS avg_load_kw,
           ROUND(MAX(load_kw), 2)         AS peak_load_kw,
           ROUND(MAX(meter_kwh)
                 - MIN(meter_kwh), 2)     AS energy_kwh,
           SUM(CASE WHEN status = 'FAULTED'
                    THEN 1 ELSE 0 END)    AS fault_samples,
           COUNT(*)                        AS total_samples
    FROM `fleetops`.`_default`.`telemetry`
    GROUP BY station_id, DATE_TRUNC_STR(ts, 'month')
),
monthly_sessions AS (
    SELECT station_id,
           DATE_TRUNC_STR(start_ts, 'month')   AS month,
           COUNT(*)                              AS total_sessions,
           ROUND(SUM(kwh_delivered), 2)          AS total_kwh,
           ROUND(AVG(kwh_delivered), 2)          AS avg_kwh_per_session
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED'
    GROUP BY station_id, DATE_TRUNC_STR(start_ts, 'month')
)
SELECT t.station_id,
       t.month,
       t.avg_load_kw,
       t.peak_load_kw,
       t.energy_kwh          AS telemetry_energy_kwh,
       s.total_sessions,
       s.total_kwh           AS session_energy_kwh,
       s.avg_kwh_per_session,
       ROUND(t.fault_samples * 100.0
             / NULLIF(t.total_samples, 0), 2) AS fault_pct
FROM monthly_telemetry t
LEFT JOIN monthly_sessions s
       ON t.station_id = s.station_id AND t.month = s.month
ORDER BY t.month DESC, t.station_id;
```

---

## Part 3 — Window Functions

A window function computes a value across a set of rows related to the current
row — without collapsing them into a single group like `GROUP BY` does. The
`OVER (...)` clause defines the window.

### Beginner

**3a. Rank stations by current load**

```sql
SELECT serial,
       name,
       status,
       meter_kwh,
       RANK() OVER (ORDER BY meter_kwh DESC)        AS energy_rank,
       DENSE_RANK() OVER (ORDER BY meter_kwh DESC)  AS energy_dense_rank
FROM `fleetops`.`_default`.`stations`
ORDER BY energy_rank;
```

> `RANK()` leaves gaps after ties (1, 2, 2, 4). `DENSE_RANK()` does not (1, 2, 2, 3).

---

**3b. Number each work order per technician**

```sql
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
```

> `PARTITION BY assignee` restarts the counter for each technician.

---

**3c. Running total of energy delivered per station**

```sql
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
```

---

### Intermediate

**3d. Compare each reading to the previous one — load change per tick**

```sql
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
```

> `LAG(col, 1)` fetches the value from the previous row in the window.
> `LEAD(col, 1)` fetches the value from the *next* row.

---

**3e. Session length and how it compares to the station average**

```sql
SELECT station_id,
       id AS session_id,
       start_ts,
       end_ts,
       kwh_delivered,
       ROUND(DATE_DIFF_STR(end_ts, start_ts, 'minute'), 0)   AS duration_min,
       ROUND(AVG(DATE_DIFF_STR(end_ts, start_ts, 'minute'))
             OVER (PARTITION BY station_id), 0)               AS avg_duration_min,
       ROUND(DATE_DIFF_STR(end_ts, start_ts, 'minute')
             - AVG(DATE_DIFF_STR(end_ts, start_ts, 'minute'))
               OVER (PARTITION BY station_id), 0)             AS diff_from_avg_min
FROM `fleetops`.`_default`.`sessions`
WHERE state = 'COMPLETED'
  AND end_ts IS NOT NULL
ORDER BY station_id, start_ts;
```

---

**3f. Percent of total fleet energy per station**

```sql
SELECT station_id,
       ROUND(SUM(kwh_delivered), 2)   AS station_kwh,
       ROUND(SUM(SUM(kwh_delivered)) OVER (), 2)  AS fleet_total_kwh,
       ROUND(
           SUM(kwh_delivered) * 100.0
           / SUM(SUM(kwh_delivered)) OVER (),
       2) AS pct_of_fleet
FROM `fleetops`.`_default`.`sessions`
WHERE state = 'COMPLETED'
GROUP BY station_id
ORDER BY station_kwh DESC;
```

> `OVER ()` with no `PARTITION BY` means the entire result set is the window —
> giving you a grand total you can divide by.

---

### Advanced

**3g. Top-3 readings per station by load — per-partition Top-N**

```sql
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
```

---

**3h. Session streaks — consecutive charging sessions with no gap > 30 min**

```sql
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
       COUNT(*)                         AS sessions_in_streak,
       MIN(start_ts)                    AS streak_start,
       MAX(end_ts)                      AS streak_end,
       ROUND(SUM(kwh_delivered), 2)     AS total_kwh_in_streak
FROM streak_groups
GROUP BY station_id, streak_id
HAVING COUNT(*) > 1
ORDER BY sessions_in_streak DESC;
```

---

**3i. Percentile buckets — which stations are in the top 25% for energy delivered**

```sql
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
```

> `NTILE(4)` divides rows into 4 equal buckets. Use `NTILE(100)` for percentiles.

---

### Export Queries

**3j. Station performance scorecard — one row per station, all KPIs**

```sql
WITH telemetry_stats AS (
    SELECT station_id,
           COUNT(*)                          AS total_readings,
           ROUND(AVG(load_kw), 2)           AS avg_load_kw,
           ROUND(MAX(load_kw), 2)           AS peak_load_kw,
           ROUND(AVG(temperature_c), 1)     AS avg_temp_c,
           SUM(CASE WHEN status = 'FAULTED'
                    THEN 1 ELSE 0 END)      AS fault_count
    FROM `fleetops`.`_default`.`telemetry`
    GROUP BY station_id
),
session_stats AS (
    SELECT station_id,
           COUNT(*)                              AS total_sessions,
           ROUND(SUM(kwh_delivered), 2)          AS total_kwh,
           ROUND(AVG(kwh_delivered), 2)          AS avg_kwh_per_session,
           ROUND(AVG(DATE_DIFF_STR(
               end_ts, start_ts, 'minute')), 0)  AS avg_session_min
    FROM `fleetops`.`_default`.`sessions`
    WHERE state = 'COMPLETED' AND end_ts IS NOT NULL
    GROUP BY station_id
),
work_stats AS (
    SELECT station_id,
           COUNT(*) AS total_work_orders,
           SUM(CASE WHEN status IN ('OPEN','IN_PROGRESS')
                    THEN 1 ELSE 0 END) AS open_orders,
           SUM(CASE WHEN priority = 'CRITICAL'
                    THEN 1 ELSE 0 END) AS critical_orders
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
             / NULLIF(t.total_readings, 0), 2)  AS fault_rate_pct,
       -- Session KPIs
       ss.total_sessions,
       ss.total_kwh,
       ss.avg_kwh_per_session,
       ss.avg_session_min,
       -- Work order KPIs
       COALESCE(w.total_work_orders, 0)  AS total_work_orders,
       COALESCE(w.open_orders, 0)        AS open_work_orders,
       COALESCE(w.critical_orders, 0)    AS critical_work_orders,
       -- Window: rank by total energy
       RANK() OVER (ORDER BY COALESCE(ss.total_kwh, 0) DESC) AS energy_rank
FROM `fleetops`.`_default`.`stations` s
LEFT JOIN telemetry_stats t  ON s.serial = t.station_id
LEFT JOIN session_stats   ss ON s.serial = ss.station_id
LEFT JOIN work_stats      w  ON s.serial = w.station_id
ORDER BY energy_rank;
```

---

**3k. Work order aging report — how long each open order has been waiting**

```sql
SELECT id,
       title,
       priority,
       status,
       assignee,
       station_id,
       created_ts,
       ROUND(DATE_DIFF_STR(NOW_STR(), created_ts, 'hour'), 0) AS age_hours,
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
```

---

## Quick Reference

### Timestamp functions

| Function | What it does |
|----------|-------------|
| `NOW_STR()` | Current time as ISO 8601 string |
| `NOW_MILLIS()` | Current time as epoch milliseconds |
| `DATE_TRUNC_STR(ts, 'hour')` | Round timestamp down to hour |
| `DATE_PART_STR(ts, 'hour')` | Extract the hour component (0–23) |
| `DATE_ADD_STR(ts, -1, 'day')` | Subtract 1 day from a timestamp |
| `DATE_DIFF_STR(ts1, ts2, 'minute')` | Difference between two timestamps |
| `STR_TO_MILLIS(ts)` | ISO string → epoch milliseconds |
| `MILLIS_TO_STR(ms)` | Epoch milliseconds → ISO string |

### Window function frame clauses

| Clause | Meaning |
|--------|---------|
| `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | All rows from the start to here |
| `ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING` | Previous row, this row, next row |
| `RANGE BETWEEN 300000 PRECEDING AND CURRENT ROW` | Last 5 min (when ordered by ms) |
| `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` | Entire partition |

### Common window functions

| Function | Use case |
|----------|---------|
| `ROW_NUMBER()` | Unique sequential number per partition |
| `RANK()` | Rank with gaps after ties |
| `DENSE_RANK()` | Rank without gaps |
| `NTILE(n)` | Divide into n equal buckets |
| `LAG(col, n)` | Value from n rows before |
| `LEAD(col, n)` | Value from n rows ahead |
| `FIRST_VALUE(col)` | First value in the window frame |
| `LAST_VALUE(col)` | Last value in the window frame |
| `SUM/AVG/COUNT(col) OVER (...)` | Running or partitioned aggregates |
