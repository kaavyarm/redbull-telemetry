"""Rule-based findings: pure functions over already-computed data (a
`context` dict assembled by insights/service.py from derived_metrics rows,
laps, and session_results), each returning zero or more finding dicts
matching supabase/schema.sql's insight_findings shape. Adding a rule is
"write a function, append it to RULES" -- evaluate_all_rules() doesn't
change.

Thresholds here are a first, deliberately simple cut -- tunable constants,
not derived from any statistical study, flagged as such rather than
presented as more rigorous than they are.
"""
import pandas as pd

from insights.aggregation import RED_BULL_TEAM_ID, compute_field_average_degradation

SECTOR_COLUMNS = ("sector1_time_s", "sector2_time_s", "sector3_time_s")


def _name(context: dict, driver_id: str) -> str:
    """Display name for a driver_id in message text -- rule functions only
    ever handle raw ids ("hadjar", "max_verstappen"), but the persisted
    message should read the way the card title already does. Falls back to
    the raw id if this driver isn't in context (defensive, shouldn't happen
    for anyone in session_results)."""
    return (context.get("driver_names") or {}).get(driver_id, driver_id)


def _finding(session_id, finding_type, severity, subject_driver_id, compared_against_type, message, *,
             compared_against_driver_id=None, compared_against_team_id=None,
             metric_value=None, threshold_value=None, unit=None, subject=None):
    return {
        "session_id": session_id,
        "finding_type": finding_type,
        "severity": severity,
        "subject_driver_id": subject_driver_id,
        "compared_against_type": compared_against_type,
        "compared_against_driver_id": compared_against_driver_id,
        "compared_against_team_id": compared_against_team_id,
        "metric_value": metric_value,
        "threshold_value": threshold_value,
        "unit": unit,
        "subject": subject or {},
        "message": message,
    }


def rule_stint_degradation_vs_field(context: dict) -> list[dict]:
    session_id = context["session_id"]
    degradation = context["degradation_with_team"]  # driver_id, stint_number, slope_s_per_lap, confidence, team_id
    if degradation.empty:
        return []

    field_avg = compute_field_average_degradation(degradation)
    if field_avg is None or field_avg <= 0:
        return []  # no meaningful positive baseline to compare against

    findings = []
    rb_stints = degradation[
        (degradation["team_id"] == RED_BULL_TEAM_ID) & (degradation["confidence"].isin(["medium", "high"]))
    ]
    for _, row in rb_stints.iterrows():
        slope = row["slope_s_per_lap"]
        if slope is None or pd.isna(slope) or slope <= field_avg:
            continue
        ratio = slope / field_avg
        if ratio > 1.6:
            severity = "high"
        elif ratio > 1.3:
            severity = "medium"
        else:
            continue
        findings.append(_finding(
            session_id, "stint_degradation_vs_field", severity, row["driver_id"], "field_avg",
            f"Stint {int(row['stint_number'])} degradation ({slope:.3f}s/lap) is "
            f"{ratio:.1f}x the field average ({field_avg:.3f}s/lap).",
            metric_value=float(slope), threshold_value=float(field_avg), unit="s_per_lap",
            subject={"stint_number": int(row["stint_number"])},
        ))
    return findings


def rule_sector_time_vs_teammate(context: dict) -> list[dict]:
    session_id = context["session_id"]
    laps = context["red_bull_sector_laps"]  # driver_id, lap_number, sector1/2/3_time_s -- clean laps only
    rb_drivers = context["red_bull_driver_ids"]
    if len(rb_drivers) != 2 or laps.empty:
        return []  # need exactly a teammate pair to compare

    driver_a, driver_b = sorted(rb_drivers)
    laps_a = laps[laps["driver_id"] == driver_a].set_index("lap_number")
    laps_b = laps[laps["driver_id"] == driver_b].set_index("lap_number")
    shared_laps = laps_a.index.intersection(laps_b.index)
    if len(shared_laps) < 3:
        return []  # too few shared clean laps for a stable signal

    findings = []
    for sector_col in SECTOR_COLUMNS:
        deltas = (laps_b.loc[shared_laps, sector_col] - laps_a.loc[shared_laps, sector_col]).dropna()
        if len(deltas) < 3:
            continue
        median_delta = float(deltas.median())
        magnitude = abs(median_delta)
        if magnitude > 0.5:
            severity = "high"
        elif magnitude > 0.3:
            severity = "medium"
        elif magnitude > 0.15:
            severity = "low"
        else:
            continue
        slower, faster = (driver_b, driver_a) if median_delta > 0 else (driver_a, driver_b)
        sector_label = sector_col.replace("_time_s", "")
        findings.append(_finding(
            session_id, "sector_time_vs_teammate", severity, slower, "teammate",
            f"{_name(context, slower)} is {magnitude:.3f}s slower than teammate {_name(context, faster)} "
            f"in {sector_label} (median over {len(deltas)} shared clean laps).",
            compared_against_driver_id=faster, metric_value=magnitude, threshold_value=0.15, unit="s",
            subject={"sector": sector_label},
        ))
    return findings


def rule_time_left_on_table(context: dict) -> list[dict]:
    session_id = context["session_id"]
    optimal_by_driver = context["time_left_on_table_by_driver"]  # driver_id -> seconds
    rb_drivers = context["red_bull_driver_ids"]
    threshold = 0.4

    findings = []
    for driver_id in rb_drivers:
        value = optimal_by_driver.get(driver_id)
        if value is None or value <= threshold:
            continue
        severity = "high" if value > threshold * 2 else "medium"
        findings.append(_finding(
            session_id, "time_left_on_table", severity, driver_id, "session_optimal",
            f"{_name(context, driver_id)} left {value:.3f}s on the table this session vs. the theoretical "
            f"optimal lap.",
            metric_value=float(value), threshold_value=threshold, unit="s",
        ))
    return findings


def rule_braking_efficiency_vs_teammate(context: dict) -> list[dict]:
    session_id = context["session_id"]
    brake_pct = context["red_bull_brake_pct_by_driver"]  # driver_id -> % of fastest-lap time spent braking
    rb_drivers = context["red_bull_driver_ids"]
    if len(rb_drivers) != 2:
        return []

    driver_a, driver_b = sorted(rb_drivers)
    pct_a, pct_b = brake_pct.get(driver_a), brake_pct.get(driver_b)
    if pct_a is None or pct_b is None or pct_a <= 0 or pct_b <= 0:
        return []

    if pct_b >= pct_a:
        subject, compared, higher_pct, lower_pct = driver_b, driver_a, pct_b, pct_a
    else:
        subject, compared, higher_pct, lower_pct = driver_a, driver_b, pct_a, pct_b
    rel_diff = (higher_pct / lower_pct) - 1
    if rel_diff <= 0.15:
        return []
    severity = "high" if rel_diff > 0.35 else "medium"
    return [_finding(
        session_id, "braking_efficiency_vs_teammate", severity, subject, "teammate",
        f"{_name(context, subject)} spent {higher_pct:.1f}% of their fastest lap on the brakes, "
        f"{rel_diff * 100:.0f}% more than teammate {_name(context, compared)} ({lower_pct:.1f}%).",
        compared_against_driver_id=compared, metric_value=float(higher_pct), threshold_value=float(lower_pct),
        unit="pct",
    )]


def rule_pace_consistency_vs_teammate(context: dict) -> list[dict]:
    session_id = context["session_id"]
    laps = context["red_bull_stint_laps"]  # driver_id, stint_number, lap_time_s -- clean laps only
    rb_drivers = context["red_bull_driver_ids"]
    if len(rb_drivers) != 2 or laps.empty:
        return []

    driver_a, driver_b = sorted(rb_drivers)
    findings = []
    for stint_number in sorted(laps["stint_number"].dropna().unique()):
        stint_laps = laps[laps["stint_number"] == stint_number]
        a_laps = stint_laps.loc[stint_laps["driver_id"] == driver_a, "lap_time_s"]
        b_laps = stint_laps.loc[stint_laps["driver_id"] == driver_b, "lap_time_s"]
        if len(a_laps) < 4 or len(b_laps) < 4:
            continue  # too few laps for a standard deviation to mean anything

        std_a, std_b = float(a_laps.std()), float(b_laps.std())
        if std_a <= 0 or std_b <= 0:
            continue
        ratio = max(std_a, std_b) / min(std_a, std_b)
        if ratio <= 1.5:
            continue

        if std_b > std_a:
            less_consistent, more_consistent, less_std, more_std, lap_count = driver_b, driver_a, std_b, std_a, len(b_laps)
        else:
            less_consistent, more_consistent, less_std, more_std, lap_count = driver_a, driver_b, std_a, std_b, len(a_laps)
        severity = "high" if ratio > 2.5 else "medium" if ratio > 1.8 else "low"
        findings.append(_finding(
            session_id, "pace_consistency_vs_teammate", severity, less_consistent, "teammate",
            f"{_name(context, less_consistent)}'s lap time in stint {int(stint_number)} varies {ratio:.1f}x "
            f"more than teammate {_name(context, more_consistent)}'s ({less_std:.3f}s vs {more_std:.3f}s "
            f"std dev over {lap_count} laps).",
            compared_against_driver_id=more_consistent, metric_value=less_std, threshold_value=more_std, unit="s",
            subject={"stint_number": int(stint_number)},
        ))
    return findings


RULES = [
    rule_stint_degradation_vs_field,
    rule_sector_time_vs_teammate,
    rule_time_left_on_table,
    rule_braking_efficiency_vs_teammate,
    rule_pace_consistency_vs_teammate,
]


def evaluate_all_rules(context: dict) -> list[dict]:
    findings = []
    for rule in RULES:
        findings.extend(rule(context))
    return findings
