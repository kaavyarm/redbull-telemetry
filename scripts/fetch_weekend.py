"""Pull one FastF1 race weekend and dump raw session data to local fixtures.

Usage:
    python scripts/fetch_weekend.py 2026 11
    python scripts/fetch_weekend.py 2026 11 --sessions R Q

Writes to data/raw/<year>/<round>_<event_slug>/<session_code>/*.parquet|json
"""
import argparse
import json
import sys
from pathlib import Path

import fastf1
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.sources import combine_driver_dict, slugify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / ".fastf1_cache"


def dump_df(df: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df is None or len(df) == 0:
        path.with_suffix(".empty").write_text("")
        return 0
    df.to_parquet(path, index=False)
    return len(df)


def fetch_session(year: int, round_number: int, session_code: str, out_dir: Path) -> dict:
    session = fastf1.get_session(year, round_number, session_code)
    session.load()

    counts = {}
    counts["laps"] = dump_df(session.laps, out_dir / "laps.parquet")
    counts["results"] = dump_df(session.results, out_dir / "results.parquet")
    counts["track_status"] = dump_df(session.track_status, out_dir / "track_status.parquet")
    counts["session_status"] = dump_df(session.session_status, out_dir / "session_status.parquet")
    counts["weather"] = dump_df(session.weather_data, out_dir / "weather.parquet")
    counts["race_control_messages"] = dump_df(
        session.race_control_messages, out_dir / "race_control_messages.parquet"
    )

    car_all = combine_driver_dict(session.car_data)
    counts["car_telemetry"] = dump_df(car_all, out_dir / "car_telemetry.parquet")

    pos_all = combine_driver_dict(session.pos_data)
    counts["position_telemetry"] = dump_df(pos_all, out_dir / "position_telemetry.parquet")

    event = session.event
    meta = {
        "year": year,
        "round": round_number,
        "session_code": session_code,
        "event_name": event["EventName"],
        "event_slug": slugify(event["EventName"]),
        "location": event.get("Location"),
        "country": event.get("Country"),
        "event_format": event.get("EventFormat"),
        "session_type": slugify(session.name),
        "session_name": session.name,
        "event_date": str(event["EventDate"]),
        "drivers": list(session.car_data.keys()),
        "row_counts": counts,
        "lap_columns": list(session.laps.columns) if session.laps is not None else [],
        "car_telemetry_columns": list(car_all.columns) if len(car_all) else [],
        "position_telemetry_columns": list(pos_all.columns) if len(pos_all) else [],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


def session_codes_for_event(year: int, round_number: int) -> list[str]:
    event = fastf1.get_event(year, round_number)
    codes = []
    for i in range(1, 6):
        try:
            name = event.get_session_name(i)
        except Exception:
            continue
        if not name or (isinstance(name, float)):
            continue
        codes.append(str(i))
    return codes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("round", type=int)
    parser.add_argument("--sessions", nargs="*", default=None, help="e.g. R Q FP1 FP2 FP3 S SQ")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(str(CACHE_DIR))

    event = fastf1.get_event(args.year, args.round)
    event_slug = slugify(event["EventName"])
    weekend_dir = RAW_DIR / str(args.year) / f"{args.round:02d}_{event_slug}"

    sessions = args.sessions or session_codes_for_event(args.year, args.round)

    summary = {}
    for code in sessions:
        try:
            session = fastf1.get_session(args.year, args.round, code)
            session_slug = slugify(session.name)
        except Exception as e:
            print(f"  skip session {code}: {e}", file=sys.stderr)
            continue
        out_dir = weekend_dir / session_slug
        print(f"[{event['EventName']}] fetching session {code} -> {session_slug}")
        try:
            meta = fetch_session(args.year, args.round, code, out_dir)
            summary[session_slug] = meta["row_counts"]
            print(f"  rows: {meta['row_counts']}")
        except Exception as e:
            print(f"  FAILED session {code} ({session_slug}): {e}", file=sys.stderr)

    (weekend_dir / "weekend_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. Weekend fixtures at {weekend_dir}")


if __name__ == "__main__":
    main()
