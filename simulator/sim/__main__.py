from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import time

from .fleet import DEFAULT_SITES, StationSim, now_iso
from .transport import Transport


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EVSE FleetOps telemetry simulator")
    p.add_argument(
        "--url",
        default=os.environ.get("EVSE_API_URL", "http://localhost:8010"),
        help="backend base URL (env EVSE_API_URL)",
    )
    p.add_argument("--interval", type=float, default=5.0, help="wall-clock seconds per tick")
    p.add_argument("--speed", type=float, default=60.0, help="simulated seconds per tick (dt)")
    p.add_argument("--stations", type=int, default=12, help="max stations to simulate")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible runs")
    p.add_argument("--no-sessions", action="store_true", help="disable session events")
    p.add_argument("--duration", type=float, default=0, help="stop after this many seconds (0 = run forever)")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("evse.sim")
    rng = random.Random(args.seed)

    transport = Transport(args.url)
    discovered = await transport.discover_stations()
    sites = discovered if discovered else DEFAULT_SITES
    sites = sites[: args.stations]
    if not sites:
        log.error("no stations discovered and no default topology available")
        return

    fleet = [
        StationSim(
            serial=s["serial"],
            name=s.get("name", ""),
            site_type=s.get("site_type", "garage"),
            model=s.get("model", "VoltHub DC 350"),
            rng=random.Random(f"{args.seed or 0}-{s['serial']}"),
        )
        for s in sites
    ]
    log.info("simulating %d stations -> %s every %.1fs (dt=%.1fs)", len(fleet), args.url, args.interval, args.speed)

    ticks = 0
    total_sent = 0
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    try:
        while deadline is None or time.monotonic() < deadline:
            ticks += 1
            ts = now_iso()
            samples = []
            session_events = []
            for station in fleet:
                sample, events = station.tick(args.speed, ts)
                samples.append(sample)
                if not args.no_sessions:
                    session_events.extend(events)
                for ev in events:
                    log.info("session %s on %s (%.2f kWh)", ev["event"], ev["station_id"], ev.get("kwh", 0))

            batch = {"samples": samples, "session_events": session_events}
            sent, dropped = await transport.send_batch(batch)
            total_sent += len(samples) if sent else 0
            if ticks % 10 == 0:
                active = sum(1 for s in fleet if s.status == "CHARGING")
                log.info(
                    "tick %d: charging=%d/%d, meters total ~%.0f kWh, buffered=%d, dropped=%d",
                    ticks,
                    active,
                    len(fleet),
                    sum(s.meter_kwh for s in fleet),
                    transport.buffered,
                    dropped,
                )
            await asyncio.sleep(args.interval)
        log.info("duration reached after %d ticks (%d samples delivered)", ticks, total_sent)
    finally:
        await transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("simulator stopped")