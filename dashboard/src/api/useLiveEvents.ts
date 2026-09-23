import { useEffect, useRef, useState } from "react";
import type { LatestReading, LiveEvent, LiveEventType } from "../types";
import { getLatest } from "./client";

const FALLBACK_POLL_MS = 15000;

// The backend sends named SSE events (`event: telemetry`, ...). EventSource only
// routes unnamed frames to `onmessage`, so each name needs its own listener.
const EVENT_TYPES: LiveEventType[] = ["snapshot", "telemetry", "status", "session", "alert", "workorder"];

/**
 * Subscribes to the backend SSE stream. Falls back to REST polling of the
 * latest readings while the stream is down (e.g. proxy/network hiccup).
 */
export function useLiveEvents(limit = 40): { events: LiveEvent[]; latest: Record<string, LatestReading> | null } {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [latest, setLatest] = useState<Record<string, LatestReading> | null>(null);
  const eventsRef = useRef<LiveEvent[]>([]);

  const push = (ev: LiveEvent) => {
    if (ev.type === "snapshot") {
      eventsRef.current = [...(ev.recent ?? [])].reverse().slice(0, limit);
      if (ev.latest) setLatest({ ...ev.latest });
    } else {
      eventsRef.current = [ev, ...eventsRef.current].slice(0, limit);
    }
    setEvents([...eventsRef.current]);

    const sid = ev.station_id;
    if (sid && (ev.type === "telemetry" || ev.type === "status")) {
      setLatest((prev) => {
        const cur = prev?.[sid];
        const next: LatestReading =
          ev.type === "telemetry"
            ? {
                station_id: sid,
                ts: ev.ts ?? "",
                status: ev.status ?? cur?.status ?? "AVAILABLE",
                meter_kwh: ev.meter_kwh ?? 0,
                temperature_c: ev.temperature_c ?? null,
                humidity_pct: ev.humidity_pct ?? null,
                vibration_mm_s: ev.vibration_mm_s ?? null,
                load_kw: ev.load_kw ?? null,
              }
            : cur
              ? { ...cur, status: ev.status ?? cur.status }
              : {
                  station_id: sid,
                  ts: ev.ts ?? "",
                  status: ev.status ?? "AVAILABLE",
                  meter_kwh: 0,
                  temperature_c: null,
                  humidity_pct: null,
                  vibration_mm_s: null,
                  load_kw: null,
                };
        return { ...(prev ?? {}), [sid]: next };
      });
    }
  };

  useEffect(() => {
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let streaming = false;

    const onEvent = (msg: MessageEvent) => {
      streaming = true;
      try {
        push(JSON.parse(msg.data) as LiveEvent);
      } catch {
        /* ignore malformed frame */
      }
    };

    const connect = () => {
      if (stopped) return;
      es = new EventSource("/api/events/stream");
      for (const type of EVENT_TYPES) es.addEventListener(type, onEvent);
      es.onerror = () => {
        streaming = false;
        es?.close();
        es = null;
        if (!stopped) retryTimer = setTimeout(connect, 3000);
      };
    };

    connect();
    const fallbackTimer = setInterval(async () => {
      if (streaming) return;
      try {
        const res = await getLatest();
        if (res?.latest) setLatest({ ...res.latest });
      } catch {
        /* backend unreachable */
      }
    }, FALLBACK_POLL_MS);

    return () => {
      stopped = true;
      if (es) es.close();
      if (retryTimer) clearTimeout(retryTimer);
      clearInterval(fallbackTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { events, latest };
}
