#!/usr/bin/env bash
# Doc-vs-reality drift check for the Domain-Library.
#
# Documentation drift is a first-class failure mode here: the operating agent
# does exactly what the most specific document says, so a stale path, a dead
# script reference, or a banned embed form in one doc becomes agent behavior.
# Run this after any docs or script change, and before any release.
#
# Usage: bash _meta/scripts/docs_drift_check.sh [library-root]
# Exit: 0 clean, 2 findings.

set -u
ROOT="${1:-.}"
cd "$ROOT" || exit 1
FINDINGS=0

note() { echo "DRIFT: $*"; FINDINGS=$((FINDINGS + 1)); }

echo "== 1. personal absolute paths in live docs/scripts =="
# /home/<user> paths make runbooks wrong for everyone else. History files
# (.orig snapshots, migration-plan, the audit report) are exempt: they are
# records of the past, not instructions.
HITS=$(grep -rn "/home/[a-z]*/" --include="*.py" --include="*.md" --include="*.sh" _meta agents ./*.md 2>/dev/null \
  | grep -v -e "Zone.Identifier" -e "\.orig" -e "docs/history/" -e "failure-archaeology" -e "docs_drift_check" -e "migration-progress" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "personal absolute paths above — replace with \$WIKI/relative paths"; fi

echo "== 2. banned 'source' embed target in live contracts/prompts/templates =="
# ![[source#^id]] is the form behind the historic 72%-dead-embeds incident.
# Scope: docs that INSTRUCT extraction (contracts, prompts, templates, the
# operating skills). The domain-library-* stewardship skills discuss the form
# as history and are exempt, as are lines that quote it in order to ban it.
HITS=$(grep -rn '\[\[source#' _meta/contracts _meta/templates agents 2>/dev/null \
  | grep -v -e "Zone.Identifier" -e "\.orig" -e "Never target" -e "never target" -e "rather than" -e "docs_drift_check" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "banned [[source# embed form in a live instruction doc"; fi

echo "== 3. smoke-test count claims vs actual =="
# Scope: normative claims only (README + operating pipeline skill). History
# narratives in stewardship skills legitimately cite old counts.
ACTUAL=$(grep -c "^def test_" _meta/scripts/library_pipeline_test_suite.py 2>/dev/null || echo 0)
echo "actual test functions: $ACTUAL"
for CLAIM in $(grep -rho "[0-9]\+ \(smoke \)\?tests" README.md agents/orchestrator/skills/domain-library-ingest-pipeline 2>/dev/null | grep -o "^[0-9]*" | sort -u); do
  if [ "$CLAIM" != "$ACTUAL" ]; then note "a doc claims $CLAIM tests; the suite defines $ACTUAL"; fi
done

echo "== 4. referenced pipeline scripts that do not exist =="
for f in $(grep -rho "_meta/scripts/[a-z0-9_]*\.py" ./*.md agents _meta/contracts 2>/dev/null | sort -u); do
  [ -f "$f" ] || note "docs reference $f but it does not exist"
done

echo "== 5. secret-shaped values in tracked .env files =="
for envf in $(find . -name ".env" -not -path "./.git/*" 2>/dev/null); do
  if grep -qE "KEY=[A-Za-z0-9._-]{20,}" "$envf" 2>/dev/null; then
    note "$envf contains a real-looking API key — must be a placeholder in a shareable repo"
  fi
done

echo "== 6. private-era banned strings =="
# Names from the pre-public private repository must never reappear in live
# docs or code. Allowlisted: docs/history/**, docs/architecture-lessons.md,
# migration-progress.md (they record the migration itself), and this script.
BANNED='Quant-Library|quantlib_|quantdefs|quantmath|quantexamples|quantwarnings|quantecontext|OMP-Quant|Niko|/home/niko|C:\\Users|~/\.omp'
HITS=$(grep -rnE "$BANNED" --include="*.py" --include="*.md" --include="*.sh" --include="*.json" _meta agents ./*.md 2>/dev/null \
  | grep -v -e "docs/history/" -e "docs/architecture-lessons.md" -e "migration-progress" -e "docs_drift_check" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "private-era banned string above — remove before release"; fi

echo
if [ "$FINDINGS" -eq 0 ]; then echo "OK: no doc drift detected"; exit 0; fi
echo "$FINDINGS drift finding(s). Fix docs and code together in one change."
exit 2
