#!/usr/bin/env bash
# Phase 1 acceptance checks against a running stack.
#
# Usage:
#   bash scripts/verify_phase1.sh [backend_base_url] [frontend_base_url]
#
# Verifies: bare /health contract, enveloped health/detail, request_id
# propagation, 404 error envelope shape, and the frontend HTML shell.
set -uo pipefail

BACKEND="${1:-http://localhost:8000}"
FRONTEND="${2:-http://localhost:3000}"
# Repo-relative (not /tmp): on Windows/git-bash curl is a native binary that
# cannot resolve MSYS-style absolute temp paths.
TMP="./.verify_tmp"
rm -rf "$TMP" && mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf '  PASS  %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL  %s\n        expected: %s\n        actual:   %s\n' "$label" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

jqp() { python -c "import json,sys;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo "<parse-error>"; }

echo "== backend: $BACKEND =="

curl -fsS "$BACKEND/health" -o "$TMP/health.json"
check "GET /health body" '{"status":"ok"}' "$(tr -d ' \r\n' < "$TMP/health.json")"

check "GET /health status" "200" "$(curl -s -o /dev/null -w '%{http_code}' "$BACKEND/health")"

curl -fsS -D "$TMP/h.txt" -o "$TMP/detail.json" "$BACKEND/api/v1/health/detail"
check "response carries X-Request-ID" "yes" \
  "$(grep -qi '^x-request-id: req_' "$TMP/h.txt" && echo yes || echo no)"
check "health/detail success" "True" "$(jqp 'd["success"]' < "$TMP/detail.json")"
check "health/detail error is null" "None" "$(jqp 'd["error"]' < "$TMP/detail.json")"
check "health/detail request_id" "yes" \
  "$(jqp '"yes" if d["request_id"].startswith("req_") else "no"' < "$TMP/detail.json")"
check "database component up" "up" \
  "$(jqp '[c["status"] for c in d["data"]["components"] if c["name"]=="database"][0]' < "$TMP/detail.json")"
check "redis component up" "up" \
  "$(jqp '[c["status"] for c in d["data"]["components"] if c["name"]=="redis"][0]' < "$TMP/detail.json")"
check "health/detail does not leak fields" "success,data,error,request_id" \
  "$(jqp '",".join(d.keys())' < "$TMP/detail.json")"

curl -fsS -H 'X-Request-ID: req_caller_id_123' -o "$TMP/echo.json" "$BACKEND/api/v1/health/detail"
check "caller-supplied request id preserved" "req_caller_id_123" \
  "$(jqp 'd["request_id"]' < "$TMP/echo.json")"

check "404 status code" "404" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BACKEND/api/v1/nope")"

curl -s -o "$TMP/404.json" "$BACKEND/api/v1/nope"
check "404 error code" "NOT_FOUND" "$(jqp 'd["error"]["code"]' < "$TMP/404.json")"
check "404 success flag" "False" "$(jqp 'd["success"]' < "$TMP/404.json")"
check "404 data is null" "None" "$(jqp 'd["data"]' < "$TMP/404.json")"

check "405 is enveloped" "METHOD_NOT_ALLOWED" \
  "$(curl -s -X POST "$BACKEND/health" | jqp 'd["error"]["code"]')"

echo "== frontend: $FRONTEND =="
curl -fsS "$FRONTEND" -o "$TMP/index.html"
check "frontend serves HTML" "yes" "$(grep -qi '<html' "$TMP/index.html" && echo yes || echo no)"
check "frontend renders app name" "yes" "$(grep -q 'AI Studio' "$TMP/index.html" && echo yes || echo no)"
check "frontend status code" "200" "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND")"

echo
printf 'passed=%d failed=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
