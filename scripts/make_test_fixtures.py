"""Builds small, git-trackable fixtures under tests/fixtures/ from the full
(gitignored, 242MB) FastF1 pulls under data/raw/ -- so the test suite
(and CI, which has no FastF1 network access or 242MB to check out) can run
against real FastF1-shaped data without the full telemetry volume.

Only telemetry is trimmed (it's ~98% of a session's size); laps/results/
track_status/session_status/weather/race_control_messages are already
small (KBs) and copied through unchanged. Telemetry is evenly sampled
per-driver across the full session (not just the first N rows) so it keeps
the same time coverage the transform/cleaning logic's invariants depend on
-- e.g. samples both before and after each driver's first lap, which a
naive "keep the first N rows" trim could accidentally lose entirely.

Usage:
    python scripts/make_test_fixtures.py
"""
import json
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "data" / "raw" / "2026"
DEST_ROOT = ROOT / "tests" / "fixtures" / "2026"

# (weekend_dir, session_slug) pairs to include -- one conventional weekend,
# one sprint weekend, matching what tests/test_transform.py already covers.
SESSIONS = [
    ("11_hungarian_grand_prix", "qualifying"),
    ("09_british_grand_prix", "sprint"),
]

# Small-tables-only, no telemetry needed -- test_cleaning.py's real-data
# test only reads session_status.parquet (a real 'Aborted' mid-session
# timeline that still reaches 'Ends').
SMALL_ONLY_SESSIONS = [
    ("06_monaco_grand_prix", "practice_1"),
]

SMALL_FILES = [
    "laps.parquet", "results.parquet", "track_status.parquet", "session_status.parquet",
    "weather.parquet", "race_control_messages.parquet", "meta.json",
]
TELEMETRY_FILES = ["car_telemetry.parquet", "position_telemetry.parquet"]
TARGET_ROWS_PER_DRIVER = 300


def trim_telemetry(src: Path, dest: Path) -> tuple[int, int]:
    df = pd.read_parquet(src)
    trimmed_parts = []
    for _, g in df.groupby("DriverNumber"):
        step = max(1, len(g) // TARGET_ROWS_PER_DRIVER)
        trimmed_parts.append(g.iloc[::step])
    trimmed = pd.concat(trimmed_parts, ignore_index=True)
    trimmed.to_parquet(dest, index=False)
    return len(df), len(trimmed)


def main():
    for weekend_dir, session_slug in SESSIONS:
        src_dir = SOURCE_ROOT / weekend_dir / session_slug
        dest_dir = DEST_ROOT / weekend_dir / session_slug
        dest_dir.mkdir(parents=True, exist_ok=True)

        for name in SMALL_FILES:
            src = src_dir / name
            if src.exists():
                shutil.copy2(src, dest_dir / name)

        for name in TELEMETRY_FILES:
            src = src_dir / name
            if not src.exists():
                continue
            before, after = trim_telemetry(src, dest_dir / name)
            print(f"{weekend_dir}/{session_slug}/{name}: {before} -> {after} rows")

        meta_path = dest_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["_fixture_note"] = "telemetry trimmed for tests/fixtures/ -- see scripts/make_test_fixtures.py"
            meta_path.write_text(json.dumps(meta, indent=2))

    for weekend_dir, session_slug in SMALL_ONLY_SESSIONS:
        src_dir = SOURCE_ROOT / weekend_dir / session_slug
        dest_dir = DEST_ROOT / weekend_dir / session_slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in SMALL_FILES:
            src = src_dir / name
            if src.exists():
                shutil.copy2(src, dest_dir / name)
        print(f"{weekend_dir}/{session_slug}: small tables only (no telemetry)")

    total_size = sum(f.stat().st_size for f in DEST_ROOT.rglob("*") if f.is_file())
    print(f"\ntotal tests/fixtures/2026 size: {total_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
