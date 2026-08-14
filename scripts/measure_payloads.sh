#!/bin/bash
# Measures real payload size + response time for every query the frontend
# actually issues, against a live PostgREST instance (what Supabase's REST
# API actually is) backed by real ingested data. Run after
# scripts/ingest_weekend.py / clean_weekend.py / compute_derived_metrics.py.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:3000}"
TOKEN="$(cat /tmp/rbt_jwt.txt)"
SESSION_ID="${SESSION_ID:-1}"
DRIVER_ID="${DRIVER_ID:-norris}"
LAP_ID="${LAP_ID:-}"

measure() {
  local label="$1"
  local path="$2"
  local result
  result=$(curl -s -o /tmp/rbt_response_body -w "%{size_download} %{time_total}" \
    -H "Authorization: Bearer $TOKEN" "${BASE_URL}${path}")
  local bytes=$(echo "$result" | cut -d' ' -f1)
  local time_s=$(echo "$result" | cut -d' ' -f2)
  local kb=$(echo "scale=1; $bytes/1024" | bc)
  printf "%-45s %10s bytes  %8s KB  %8s s\n" "$label" "$bytes" "$kb" "$time_s"
}

echo "=== Session Explorer ==="
measure "listSessions()" "/sessions?select=id,season,round_number,event_name,location,country,event_format,session_type,session_name,event_date&order=event_date.desc"

echo
echo "=== Session Detail: Results tab ==="
measure "getSessionResults()" "/session_results?select=driver_id,team_id,driver_number,position,classified_position,grid_position,q1,q2,q3,finish_time,status,points,laps_completed,drivers(full_name,abbreviation,headshot_url),teams(name,color)&session_id=eq.${SESSION_ID}&order=position.asc"

echo
echo "=== Session Detail: Laps tab ==="
measure "getLapTimeEvolution(driver)" "/lap_time_evolution?select=*&session_id=eq.${SESSION_ID}&driver_id=eq.${DRIVER_ID}&order=lap_number.asc"
measure "getLaps(all, session)" "/laps?select=id,driver_id,lap_number,lap_time,compound,deleted,is_accurate,pit_in_time,pit_out_time&session_id=eq.${SESSION_ID}&order=lap_number.asc"

echo
echo "=== Session Detail: Setup tab ==="
measure "getStintPerformance()" "/stint_performance?select=*,drivers(full_name,abbreviation)&session_id=eq.${SESSION_ID}"
measure "getCompoundPaceSummary()" "/compound_pace_summary?select=*&session_id=eq.${SESSION_ID}"
measure "getSetupRevisionDeltas()" "/setup_revision_deltas?select=*,drivers(full_name,abbreviation)&session_id=eq.${SESSION_ID}"

if [ -n "$LAP_ID" ]; then
  echo
  echo "=== Session Detail: Telemetry tab (single lap) ==="
  measure "getLapTelemetry(lap_id=${LAP_ID})" "/car_telemetry_samples?select=session_time,speed,throttle,brake,n_gear,rpm,drs&session_id=eq.${SESSION_ID}&lap_id=eq.${LAP_ID}&order=session_time.asc"
fi

echo
echo "=== For comparison: what a naive 'download all telemetry' would cost ==="
measure "SELECT * car_telemetry_samples WHERE session_id (no lap filter)" "/car_telemetry_samples?select=*&session_id=eq.${SESSION_ID}"
