"""Load SessionSourceData either from a live FastF1 session or from a
pulled fixture directory on disk. Both paths converge on the same shape so
transform.py never needs to know which one fed it."""
import json
import re
from pathlib import Path

import pandas as pd

from ingest.transform import SessionMeta, SessionSourceData


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def combine_driver_dict(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for drv_num, df in data.items():
        d = df.copy()
        d["DriverNumber"] = drv_num
        frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_session_source_from_fastf1(session) -> SessionSourceData:
    event = session.event
    meta = SessionMeta(
        season=int(event["EventDate"].year),
        round_number=int(event["RoundNumber"]),
        event_name=event["EventName"],
        event_slug=slugify(event["EventName"]),
        location=event.get("Location"),
        country=event.get("Country"),
        event_format=event.get("EventFormat"),
        session_type=slugify(session.name),
        session_name=session.name,
        event_date=str(event["EventDate"].date()),
    )
    return SessionSourceData(
        meta=meta,
        laps=session.laps,
        results=session.results,
        track_status=session.track_status,
        session_status=session.session_status,
        weather=session.weather_data,
        race_control_messages=session.race_control_messages,
        car_telemetry=combine_driver_dict(session.car_data),
        position_telemetry=combine_driver_dict(session.pos_data),
    )


def load_session_source_from_fixture(weekend_dir: Path, session_slug: str) -> SessionSourceData:
    session_dir = Path(weekend_dir) / session_slug
    meta_json = json.loads((session_dir / "meta.json").read_text())

    weekend_dir_name = Path(weekend_dir).name           # '11_hungarian_grand_prix'
    round_number = int(weekend_dir_name.split("_", 1)[0])
    event_slug = weekend_dir_name.split("_", 1)[1]

    meta = SessionMeta(
        season=meta_json["year"],
        round_number=round_number,
        event_name=meta_json["event_name"],
        event_slug=meta_json.get("event_slug", event_slug),
        location=meta_json.get("location"),
        country=meta_json.get("country"),
        event_format=meta_json.get("event_format", "conventional"),
        session_type=session_slug,
        session_name=meta_json["session_name"],
        event_date=meta_json["event_date"][:10],
    )

    def _read(name: str) -> pd.DataFrame:
        p = session_dir / f"{name}.parquet"
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()

    return SessionSourceData(
        meta=meta,
        laps=_read("laps"),
        results=_read("results"),
        track_status=_read("track_status"),
        session_status=_read("session_status"),
        weather=_read("weather"),
        race_control_messages=_read("race_control_messages"),
        car_telemetry=_read("car_telemetry"),
        position_telemetry=_read("position_telemetry"),
    )
