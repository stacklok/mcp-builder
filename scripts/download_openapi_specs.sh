#!/usr/bin/env bash
# Download real OpenAPI specs for integration test fixtures.
#
# Usage:
#   ./scripts/download_openapi_specs.sh
#
# Downloads specs to tests/integration/fixtures/openapi/.
# The weather_api and minimal_api specs are synthetic (no real API)
# and are checked into the repo — this script only fetches real ones.

set -euo pipefail

OUTDIR="tests/integration/fixtures/openapi"
mkdir -p "$OUTDIR"

echo "Downloading OpenAPI specs..."

# GitHub REST API (OpenAPI 3.1, ~25MB)
echo "  github..."
curl -sL -o "$OUTDIR/github_openapi.yaml" \
  "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.yaml"

# Jira Cloud REST API (OpenAPI 3.0)
echo "  jira..."
curl -sL -o "$OUTDIR/jira_openapi.yaml" \
  "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json"

# Slack Web API (OpenAPI 2.0)
echo "  slack..."
curl -sL -o "$OUTDIR/slack_openapi.yaml" \
  "https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json"

# Google Drive API — Google publishes Discovery format, not OpenAPI.
# A community-maintained OpenAPI conversion is available from APIs-guru:
echo "  google_drive..."
curl -sL -o "$OUTDIR/google_drive_openapi.yaml" \
  "https://raw.githubusercontent.com/APIs-guru/openapi-directory/main/APIs/googleapis.com/drive/v3/openapi.yaml"

# BambooHR — no public OpenAPI spec available. Their docs page
# (https://documentation.bamboohr.com/reference) describes the API
# but doesn't serve a machine-readable spec. You'll need to either:
#   1. Export from their developer portal if you have access
#   2. Hand-curate a subset matching the scope YAML endpoints
#   3. Use a community spec if one exists
echo "  bamboohr... SKIPPED (no public OpenAPI spec — see script comments)"

echo ""
echo "Done. Downloaded specs to $OUTDIR/"
echo ""
echo "Missing specs (need manual download):"
echo "  - bamboohr_openapi.yaml"
