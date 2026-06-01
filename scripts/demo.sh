#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${GENSECOPS_DEMO_BASE_URL:-http://127.0.0.1:8000}"
DATA_DIR="${GENSECOPS_DATA_DIR:-data}"
export GENSECOPS_DATA_DIR="$DATA_DIR"
export GENSECOPS_HMAC_SECRET="${GENSECOPS_HMAC_SECRET:-demo-hmac-secret-change-me-1234567890}"
export GENSECOPS_DOWNLOAD_TOKEN="${GENSECOPS_DOWNLOAD_TOKEN:-demo-download-token-change-me-123456}"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/gensecops-demo.XXXXXX")"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

json_field() {
  python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

expect_field() {
  local payload="$1"
  local field="$2"
  local expected="$3"
  local actual
  actual="$(printf '%s' "$payload" | json_field "$field")"
  if [[ "$actual" != "$expected" ]]; then
    printf 'Expected %s=%s, received %s\n' "$field" "$expected" "$actual" >&2
    exit 1
  fi
}

pretty_json() {
  python3 -m json.tool
}

create_png() {
  python3 - "$1" <<'PY'
import base64
import pathlib
import sys

png = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
pathlib.Path(sys.argv[1]).write_bytes(base64.b64decode(png))
PY
}

find_uvicorn() {
  if [[ -x ".venv/bin/uvicorn" ]]; then
    printf '%s' ".venv/bin/uvicorn"
  elif command -v uvicorn >/dev/null 2>&1; then
    command -v uvicorn
  else
    printf 'uvicorn is missing. Install dependencies with: pip install -r requirements.txt\n' >&2
    exit 1
  fi
}

start_server_if_needed() {
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
    printf 'Using running server at %s\n' "$BASE_URL"
    return
  fi

  local uvicorn_bin
  uvicorn_bin="$(find_uvicorn)"
  "$uvicorn_bin" app.main:create_app --factory --host 127.0.0.1 --port 8000 \
    >"$TMP_DIR/server.log" 2>&1 &
  SERVER_PID="$!"

  for _ in {1..30}; do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
      printf 'Started local server at %s\n' "$BASE_URL"
      return
    fi
    sleep 0.2
  done

  printf 'Server failed to start. Log:\n' >&2
  cat "$TMP_DIR/server.log" >&2
  exit 1
}

create_png "$TMP_DIR/example.png"
start_server_if_needed

printf '\n=== 1. Safe image: ALLOW and verified download ===\n'
safe_response="$(curl -fsS -X POST "$BASE_URL/v1/moderate" \
  -F 'prompt=draw a safe corporate illustration')"
printf '%s' "$safe_response" | pretty_json
expect_field "$safe_response" verdict ALLOW
artifact_id="$(printf '%s' "$safe_response" | json_field artifact_id)"
download_status="$(curl -sS -o "$TMP_DIR/downloaded.png" -w '%{http_code}' \
  "$BASE_URL/v1/download/$artifact_id" \
  -H "Authorization: Bearer $GENSECOPS_DOWNLOAD_TOKEN")"
[[ "$download_status" == "200" ]] || { printf 'Expected download HTTP 200, got %s\n' "$download_status" >&2; exit 1; }
printf 'Verified download: HTTP %s\n' "$download_status"

printf '\n=== 2. Unsafe mock output: BLOCK after quarantine ===\n'
unsafe_response="$(curl -fsS -X POST "$BASE_URL/v1/moderate" \
  -F "generated_image=@$TMP_DIR/example.png;filename=unsafe-violence.png;type=image/png")"
printf '%s' "$unsafe_response" | pretty_json
expect_field "$unsafe_response" verdict BLOCK

printf '\n=== 3. PII input: BLOCK before generation and release ===\n'
pii_response="$(curl -fsS -X POST "$BASE_URL/v1/moderate" \
  -F "input_image=@$TMP_DIR/example.png;filename=passport-card.png;type=image/png")"
printf '%s' "$pii_response" | pretty_json
expect_field "$pii_response" verdict BLOCK

printf '\n=== 4. Detector failure: fail closed ===\n'
failure_response="$(curl -fsS -X POST "$BASE_URL/v1/moderate" \
  -F "generated_image=@$TMP_DIR/example.png;filename=detector_error.png;type=image/png")"
printf '%s' "$failure_response" | pretty_json
expect_field "$failure_response" verdict BLOCK

printf '\n=== 5. Tampered release: verified download returns 409 ===\n'
printf 'tampered' >"$DATA_DIR/release/$artifact_id.png"
tampered_status="$(curl -sS -o "$TMP_DIR/tampered-response.json" -w '%{http_code}' \
  "$BASE_URL/v1/download/$artifact_id" \
  -H "Authorization: Bearer $GENSECOPS_DOWNLOAD_TOKEN")"
cat "$TMP_DIR/tampered-response.json" | pretty_json
[[ "$tampered_status" == "409" ]] || { printf 'Expected tampered download HTTP 409, got %s\n' "$tampered_status" >&2; exit 1; }
printf 'Tampered download rejected: HTTP %s\n' "$tampered_status"

printf '\nDemo completed successfully. Audit: %s/audit/audit.jsonl\n' "$DATA_DIR"

