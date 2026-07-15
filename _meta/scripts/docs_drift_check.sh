#!/usr/bin/env bash
# Check documentation against the live repository layout and test inventory.
# Usage: bash _meta/scripts/docs_drift_check.sh [library-root]
# Exit: 0 clean, 2 findings.

set -u
ROOT="${1:-.}"
cd "$ROOT" || exit 1
FINDINGS=0
DOC_ROOTS=(_meta agents/orchestrator)

note() { echo "DRIFT: $*"; FINDINGS=$((FINDINGS + 1)); }

echo "== 1. personal absolute paths in live docs/scripts =="
HITS=$(grep -rn "/home/[a-z]*/" --include="*.py" --include="*.md" --include="*.sh" "${DOC_ROOTS[@]}" ./*.md 2>/dev/null \
  | grep -v -e "Zone.Identifier" -e "\.orig" -e "docs/history/" -e "docs_drift_check" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "personal absolute paths above — replace with repo-relative paths"; fi

echo "== 2. banned 'source' embed target in live contracts/prompts/templates =="
HITS=$(grep -rn '\[\[source#' _meta/contracts _meta/templates agents/orchestrator/skills 2>/dev/null \
  | grep -v -e "Zone.Identifier" -e "\.orig" -e "Never target" -e "never target" -e "rather than" -e "docs_drift_check" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "banned [[source# embed form in a live instruction doc"; fi

echo "== 3. smoke-test claims and catalog =="
SUITE=_meta/scripts/library_pipeline_test_suite.py
CATALOG=agents/orchestrator/skills/domain-library-ingest-pipeline/references/test-suite.md
ACTUAL=$(grep -c '^def test_' "$SUITE" 2>/dev/null || echo 0)
echo "actual test functions: $ACTUAL"
for CLAIM in $(grep -rhoE '[0-9]+ (smoke )?tests' README.md agents/orchestrator/skills 2>/dev/null | grep -oE '^[0-9]+' | sort -u); do
  if [ "$CLAIM" != "$ACTUAL" ]; then note "a doc claims $CLAIM tests; the suite defines $ACTUAL"; fi
done
SUITE_NAMES=$(grep '^def test_' "$SUITE" | sed -E 's/^def (test_[^(]+).*/\1/' | sort)
CATALOG_NAMES=$(grep -oE '`test_[^`]+`' "$CATALOG" | tr -d '`' | sort -u)
CATALOG_COUNT=$(printf '%s\n' "$CATALOG_NAMES" | sed '/^$/d' | wc -l)
echo "catalogued test rows: $CATALOG_COUNT"
MISSING=$(comm -23 <(printf '%s\n' "$SUITE_NAMES") <(printf '%s\n' "$CATALOG_NAMES"))
EXTRA=$(comm -13 <(printf '%s\n' "$SUITE_NAMES") <(printf '%s\n' "$CATALOG_NAMES"))
if [ -n "$MISSING" ]; then echo "$MISSING"; note "suite tests above are missing from the catalog"; fi
if [ -n "$EXTRA" ]; then echo "$EXTRA"; note "catalog tests above do not exist in the suite"; fi

echo "== 4. referenced pipeline scripts that do not exist =="
for f in $(grep -rhoE '_meta/scripts/[a-z0-9_]+\.py' ./*.md "${DOC_ROOTS[@]}" 2>/dev/null | sort -u); do
  [ -f "$f" ] || note "docs reference $f but it does not exist"
done

echo "== 5. secret-shaped values in local .env files =="
while IFS= read -r envf; do
  if grep -qE 'KEY=[A-Za-z0-9._-]{20,}' "$envf" 2>/dev/null; then
    note "$envf contains a real-looking API key"
  fi
done < <(find . -name .env -not -path './.git/*' 2>/dev/null)

echo "== 6. private-era banned strings =="
BANNED='Quant-Library|quantlib_|quantdefs|quantmath|quantexamples|quantwarnings|quantecontext|OMP-Quant|/home/niko|C:\\Users|~/\.omp'
HITS=$(grep -rnE "$BANNED" --include="*.py" --include="*.md" --include="*.sh" --include="*.json" "${DOC_ROOTS[@]}" ./*.md 2>/dev/null \
  | grep -v -e "docs/history/" -e "docs_drift_check" || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "private-era banned string above — remove before release"; fi

echo "== 7. referenced repo paths that do not exist =="
# Scope: path-shaped references into trees that must always resolve.
# Excludes templated paths ($SLUG, <slug>) by charset.
for f in $(grep -rhoE '(_meta/(scripts|schemas|agents|contracts|config|templates)|agents/orchestrator)/[A-Za-z0-9_./-]+\.(py|md|json|sh)' \
    ./*.md agents _meta/scripts library.py 2>/dev/null | sort -u); do
  [ -e "$f" ] || note "referenced path $f does not exist"
done

echo "== 8. retired public skill paths =="
HITS=$(grep -rn 'agents/skills/domain-library' --include="*.py" --include="*.md" --include="*.sh" "${DOC_ROOTS[@]}" ./*.md 2>/dev/null \
  | grep -v 'docs_drift_check.sh' || true)
if [ -n "$HITS" ]; then echo "$HITS"; note "retired agents/skills path above — use agents/orchestrator/skills"; fi

echo
if [ "$FINDINGS" -eq 0 ]; then echo "OK: no doc drift detected"; exit 0; fi
echo "$FINDINGS drift finding(s). Fix docs and code together in one change."
exit 2
