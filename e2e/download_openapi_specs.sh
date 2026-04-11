#!/usr/bin/env bash
# Download real OpenAPI specs for e2e testing.
#
# Usage:
#   ./e2e/download_openapi_specs.sh
#
# Downloads specs to e2e/fixtures/real/ alongside their scope YAMLs.
# The synthetic fixtures (weather_api, minimal_api) are checked into
# the repo under e2e/fixtures/synthetic/ — this script only fetches
# specs for real APIs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTDIR="$SCRIPT_DIR/fixtures/real"
mkdir -p "$OUTDIR"

echo "Downloading OpenAPI specs to $OUTDIR..."

# GitHub REST API (OpenAPI 3.1, ~25MB)
echo "  github..."
curl -sL -o "$OUTDIR/github_openapi.yaml" \
  "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.yaml"

# Jira Cloud REST API (OpenAPI 3.0)
echo "  jira..."
curl -sL -o "$OUTDIR/jira_openapi.yaml" \
  "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json"

# Slack Web API (Swagger 2.0 — download then convert to OpenAPI 3.0)
echo "  slack..."
curl -sL -o "$OUTDIR/slack_swagger2.json" \
  "https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json"

if command -v swagger2openapi &> /dev/null; then
  swagger2openapi "$OUTDIR/slack_swagger2.json" -o "$OUTDIR/slack_openapi.yaml" --yaml
  rm "$OUTDIR/slack_swagger2.json"
  echo "    converted to OpenAPI 3.0"
else
  echo "    WARNING: swagger2openapi not found. Install with: npm install -g swagger2openapi"
  echo "    Slack spec left as Swagger 2.0 (will not work with mcp-builder)"
  mv "$OUTDIR/slack_swagger2.json" "$OUTDIR/slack_openapi.yaml"
fi

# Google Drive API — community-maintained OpenAPI conversion from APIs-guru
echo "  google_drive..."
curl -sL -o "$OUTDIR/google_drive_openapi.yaml" \
  "https://raw.githubusercontent.com/APIs-guru/openapi-directory/main/APIs/googleapis.com/drive/v3/openapi.yaml"

# BambooHR — no public OpenAPI spec available.
# https://documentation.bamboohr.com/reference describes the API but
# doesn't serve a machine-readable spec. Options:
#   1. Export from their developer portal if you have access
#   2. Hand-curate a subset matching the scope YAML endpoints
echo "  bamboohr... SKIPPED (no public OpenAPI spec)"

echo ""
echo "Done. Missing: bamboohr_openapi.yaml (no public spec)"
