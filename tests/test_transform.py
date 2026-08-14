"""Unit tests for ingest/transform.py against real FastF1 pulls.
tests/fixtures/2026/ is a small, git-tracked, telemetry-trimmed copy of two
real sessions from the full (gitignored, 242MB) data/raw/2026/ pulls -- see
scripts/make_test_fixtures.py -- so this runs in CI without either FastF1
network access or committing the full pull. No database involved -- these
test the pure transform logic only.
"""
from pathlib import Path

import pandas as pd
import pytest

from ingest.sources import load_session_source_from_fixture
from ingest.transform import transform_session

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "2026"

# Qualifying is a real race weekend session, but much smaller than a race
# session (hundreds of thousands vs. millions of telemetry rows), which
# keeps the test suite fast without testing against synthetic data.
HUNGARY_WEEKEND = FIXTURE_ROOT / "11_hungarian_grand_prix"
HUNGARY_QUALIFYING = "qualifying"

# The one sprint-format weekend in the fixture set -- confirms the
# transform doesn't special-case conventional-weekend session slugs.
BRITAIN_WEEKEND = FIXTURE_ROOT / "09_british_grand_prix"
BRITAIN_SPRINT = "sprint"


@pytest.fixture(scope="module")
def hungary_quali():
    source = load_session_source_from_fixture(HUNGARY_WEEKEND, HUNGARY_QUALIFYING)
    return source, transform_session(source)


@pytest.fixture(scope="module")
def britain_sprint():
    source = load_session_source_from_fixture(BRITAIN_WEEKEND, BRITAIN_SPRINT)
    return source, transform_session(source)


def test_session_meta_matches_fixture_directory(hungary_quali):
    source, t = hungary_quali
    assert t.meta.season == 2026
    assert t.meta.round_number == 11
    assert t.meta.event_slug == "hungarian_grand_prix"
    assert t.meta.session_type == "qualifying"
    assert t.meta.event_format == "conventional"


def test_sprint_weekend_session_type_not_special_cased(britain_sprint):
    source, t = britain_sprint
    assert t.meta.session_type == "sprint"
    assert t.meta.event_format == "sprint_qualifying"
    assert len(t.laps) == len(source.laps)


def test_teams_and_drivers_deduplicated_from_results(hungary_quali):
    source, t = hungary_quali
    assert len(t.teams) == source.results["TeamId"].nunique()
    assert len(t.drivers) == source.results["DriverId"].nunique()
    assert set(t.teams["id"]) == set(source.results["TeamId"])
    assert set(t.drivers["id"]) == set(source.results["DriverId"])


def test_team_colors_get_hash_prefix(hungary_quali):
    _, t = hungary_quali
    assert not t.teams.empty
    assert (t.teams["color"].dropna().str.startswith("#")).all()


def test_session_results_row_per_driver(hungary_quali):
    source, t = hungary_quali
    assert len(t.session_results) == len(source.results)
    # every driver_id resolved -- no unmapped DriverNumber
    assert t.session_results["driver_id"].notna().all()


def test_laps_row_count_matches_source(hungary_quali):
    source, t = hungary_quali
    assert len(t.laps) == len(source.laps)


def test_laps_driver_id_resolved_for_every_row(hungary_quali):
    _, t = hungary_quali
    assert t.laps["driver_id"].notna().all()


def test_laps_preserve_pit_and_deletion_flags(hungary_quali):
    source, t = hungary_quali
    # PitInTime/PitOutTime are flags-by-presence in the source -- confirm
    # the same non-null counts survive the transform untouched.
    assert t.laps["pit_in_time"].notna().sum() == source.laps["PitInTime"].notna().sum()
    assert t.laps["pit_out_time"].notna().sum() == source.laps["PitOutTime"].notna().sum()
    assert t.laps["deleted"].sum() == source.laps["Deleted"].sum()
    # every deleted lap keeps a non-empty reason
    deleted = t.laps[t.laps["deleted"]]
    if len(deleted):
        assert deleted["deleted_reason"].notna().all()
        assert (deleted["deleted_reason"] != "").all()


def test_laps_unique_per_driver_and_lap_number(hungary_quali):
    """Matches schema.sql's unique(session_id, driver_id, lap_number) --
    if this fails, the idempotent upsert in ingest/db.py would fail too."""
    _, t = hungary_quali
    key = list(zip(t.laps["driver_id"], t.laps["lap_number"], strict=True))
    assert len(key) == len(set(key))


def test_stints_unique_per_driver_and_stint_number(hungary_quali):
    """Matches schema.sql's unique(session_id, driver_id, stint_number)."""
    _, t = hungary_quali
    key = list(zip(t.stints["driver_number"], t.stints["stint_number"], strict=True))
    assert len(key) == len(set(key))


def test_stints_lap_ranges_cover_every_lap_exactly_once(hungary_quali):
    source, t = hungary_quali
    total_laps_in_stints = (t.stints["lap_end"] - t.stints["lap_start"] + 1).sum()
    assert total_laps_in_stints == len(source.laps.dropna(subset=["Stint"]))


def test_setup_revisions_align_with_stints(hungary_quali):
    _, t = hungary_quali
    setup_keys = set(zip(t.setup_revisions["driver_number"], t.setup_revisions["stint_number"], strict=True))
    stint_keys = set(zip(t.stints["driver_number"], t.stints["stint_number"], strict=True))
    assert setup_keys == stint_keys


def test_race_control_message_details_only_has_populated_fields(hungary_quali):
    source, t = hungary_quali
    if source.race_control_messages.empty:
        pytest.skip("no race control messages in this fixture")
    for details in t.race_control_messages["details"]:
        assert isinstance(details, dict)
        # a "lap deletion" style message should carry racing_number, not every field
        assert all(v is not None for v in details.values())


def test_car_telemetry_row_count_matches_source(hungary_quali):
    source, t = hungary_quali
    assert len(t.car_telemetry_samples) == len(source.car_telemetry)


def test_car_and_position_telemetry_row_counts_independent_of_each_other(hungary_quali):
    """car_telemetry and position_telemetry are independently clocked
    streams -- the transform must carry each source's row count through
    untouched rather than forcing them into a shared shape."""
    source, t = hungary_quali
    assert len(t.car_telemetry_samples) == len(source.car_telemetry)
    assert len(t.position_telemetry_samples) == len(source.position_telemetry)


def test_telemetry_driver_id_resolved_for_every_row(hungary_quali):
    _, t = hungary_quali
    assert t.car_telemetry_samples["driver_id"].notna().all()
    assert t.position_telemetry_samples["driver_id"].notna().all()


def test_telemetry_lap_number_within_actual_lap_bounds(hungary_quali):
    """Where a telemetry sample was assigned a lap_number, that lap number
    must actually exist for that driver in this session -- the assignment
    logic must never invent a lap."""
    _, t = hungary_quali
    valid_laps = set(zip(t.laps["driver_id"], t.laps["lap_number"], strict=True))
    assigned = t.car_telemetry_samples.dropna(subset=["lap_number"])
    sample_keys = set(zip(assigned["driver_id"], assigned["lap_number"].astype(int), strict=True))
    assert sample_keys.issubset(valid_laps)


def test_unassigned_telemetry_precedes_each_drivers_first_lap(hungary_quali):
    """A meaningful chunk of car_telemetry legitimately has no lap_number --
    FastF1 logs telemetry for the whole session (garage time, grid, formation
    lap for a race; long garage waits between runs for qualifying), well
    before a driver's first recorded Lap 1. Session-wide assignment rates
    vary a lot (well under 90% is normal, not a bug), so the invariant that
    actually matters is narrower: every unassigned sample for a driver comes
    strictly before that driver's own first lap start -- never after, and
    never for a driver who has laps at some other point."""
    _, t = hungary_quali
    assigned_fraction = t.car_telemetry_samples["lap_number"].notna().mean()
    assert 0 < assigned_fraction < 1  # sanity: assignment isn't silently all-or-nothing

    first_lap_start = t.laps.groupby("driver_id")["lap_start_time"].min()
    unassigned = t.car_telemetry_samples[t.car_telemetry_samples["lap_number"].isna()]
    for driver_id, grp in unassigned.groupby("driver_id"):
        assert (grp["session_time"] < first_lap_start[driver_id]).all(), (
            f"driver {driver_id} has unassigned telemetry after their first lap start"
        )


def test_transform_is_pure_and_reproducible(hungary_quali):
    """Re-running the transform on the same source data must produce
    identical output -- this is what makes ingest/db.py's delete-then-insert
    idempotency strategy actually idempotent."""
    source, t1 = hungary_quali
    t2 = transform_session(source)
    pd.testing.assert_frame_equal(t1.laps.reset_index(drop=True), t2.laps.reset_index(drop=True))
    pd.testing.assert_frame_equal(
        t1.car_telemetry_samples.reset_index(drop=True),
        t2.car_telemetry_samples.reset_index(drop=True),
    )
