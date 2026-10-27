#!/usr/bin/env bash
# Copy the previous scheduled Security run's finding set for one artifact.
# A missing run or artifact leaves DEST empty, so the first scheduled scan
# treats every current advisory as new. Later scans alert only on ids that
# were not in that set. Failures to read history do not hide a clean scan:
# the caller still gates the current findings.
set -euo pipefail

name="${1:?artifact name}"
dest="${2:?destination file}"
: > "$dest"

if [[ -z "${GH_TOKEN:-}" || -z "${GITHUB_REPOSITORY:-}" ]]; then
  echo "No GitHub token or repository; previous scheduled findings are empty."
  exit 0
fi

run_id="$(gh run list \
  --repo "$GITHUB_REPOSITORY" \
  --workflow security.yml \
  --event schedule \
  --status completed \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId // empty' || true)"

if [[ -z "$run_id" ]]; then
  echo "No completed scheduled Security run to compare against."
  exit 0
fi

tmpdir="$(mktemp -d)"
if ! gh run download "$run_id" --repo "$GITHUB_REPOSITORY" --name "$name" --dir "$tmpdir"; then
  echo "Scheduled run $run_id has no artifact $name."
  exit 0
fi

found="$(find "$tmpdir" -type f -name '*.txt' -print -quit || true)"
if [[ -n "$found" ]]; then
  cp "$found" "$dest"
  echo "Loaded previous findings for $name from run $run_id."
fi
