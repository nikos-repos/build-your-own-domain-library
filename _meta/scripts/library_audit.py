#!/usr/bin/env python3
"""
Domain Library Ingest Audit
==========================
Executable final audit for the Domain Library ingestion pipeline.
Runs after Phase 5 (Page Creation & Finalization) and enforces all checklist
items as programmatic assertions.

Exit codes:
    0 = all checks passed
    1 = one or more checks failed (see JSON report)

Usage:
    domain-library run library_audit \
        --slug example-book-slug \
        --wiki /path/to/build-your-own-domain-library \
        --report _meta/reports/audit-<slug>-YYYYMMDD.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts import scoring_layer
from _meta.scripts import source_grounding_quality
from _meta.scripts import wiki_integrity
from domain_library.pipeline.common import load_state, rel, validate_slug, write_gate, write_json, write_state


class AuditCheck:
    """Single audit check with result tracking."""
    def __init__(self, id: str, description: str, category: str, manual: bool = False):
        self.id = id
        self.description = description
        self.category = category
        self.manual = manual
        self.passed = False
        self.details = []
        self.errors = []

    def ok(self, detail: str = ""):
        self.passed = True
        if detail:
            self.details.append(detail)

    def fail(self, error: str):
        self.passed = False
        self.errors.append(error)

    def warn(self, message: str):
        self.details.append(f"WARN: {message}")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "category": self.category,
            "manual": self.manual,
            "passed": self.passed,
            "details": self.details,
            "errors": self.errors
        }


class LibraryAudit:
    def __init__(self, slug: str, wiki: Path, report: Path, ack: set = frozenset()):
        self.slug = slug
        self.wiki = wiki
        self.report = report
        self.ack = set(ack)
        self.checks: List[AuditCheck] = []
        self.concept_files: List[Path] = []
        self.all_pages: List[Path] = []
        self.chapters_dir = wiki / "raw" / "papers" / slug / "chapters"
        self.extractions_dir = wiki / "_meta" / "extractions" / slug
        self.concepts_dir = wiki / "concepts"
        self.log_file = wiki / "log.md"
        self.index_file = wiki / "index.md"

    def add_check(self, id: str, description: str, category: str, manual: bool = False) -> AuditCheck:
        check = AuditCheck(id, description, category, manual)
        self.checks.append(check)
        return check

    def _first_existing(self, *names: str) -> Path:
        """First extraction artifact that exists (current name first, then
        legacy names from pre-2026-06-11 runs); falls back to the first name."""
        for name in names:
            path = self.extractions_dir / name
            if path.exists():
                return path
        return self.extractions_dir / names[0]

    def extraction_jsons(self) -> List[Path]:
        schema_dir = self.extractions_dir / "schema"
        if schema_dir.exists():
            return sorted(path for path in schema_dir.glob("*.json") if not path.name.startswith("_"))
        skip = {"specialist-verification.json", "blockid-validation.json", "page-build-report.json", "specialist-dispatch-report.json", "specialist-dispatch-plan.json", "dispatch-result.json", "pipeline-run-manifest.json", "image-to-page-coverage.json", "lexical-overlap-report.json", "schema-validation-report.json"}
        return sorted(
            path for path in self.extractions_dir.glob("*.json")
            if not path.name.startswith("_") and not path.name.startswith("master") and not path.name.endswith("-report.json") and path.name not in skip
        )

    def load_pages(self):
        """Load concept pages created for this slug only."""
        def relevant(p: Path) -> bool:
            try:
                return self.slug in p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return False
        if self.concepts_dir.exists():
            self.concept_files = [p for p in sorted(self.concepts_dir.glob("*.md")) if relevant(p)]
        self.all_pages = self.concept_files

    def run_all(self):
        """Execute the full audit suite."""
        self.load_pages()

        # === Phase 1-2: Pre-ingest & Conversion ===
        self.check_ch01_splitting_attempted()
        self.check_ch02_block_ids_annotated()
        self.check_ch03_manifest_exists()
        self.check_ch04_no_stray_folders()

        # === Phase 3: Extraction ===
        self.check_ex06_one_chapter_per_subagent()
        self.check_ex08_toolsets_all()
        self.check_ex09_role_leaf()
        self.check_ex10_pydantic_validation()
        self.check_ex11_json_has_block_ids()
        self.check_ex12_concept_density_fields()
        self.check_ex13_generic_test()
        self.check_ex14_no_regex_fallback()

        # === Phase 4: Merge & Score ===
        self.check_sc15_scoring_layer_used()
        self.check_sc16_user_confirmed()
        self.check_sc17_blockid_validator_passed()
        self.check_sc18_no_dead_block_ids()
        self.check_sc19_latex_slugs_filtered()
        self.check_sc20_template_engine_used()
        self.check_sc21_yaml_serializer_used()
        self.check_sc22_no_yaml_errors()

        # === Phase 5: Page Quality ===
        self.check_pq23_block_embeds()
        self.check_pq24_authors_words_section()
        self.check_pq27_exact_terminology()
        self.check_pq28_specific_examples()
        self.check_pq29_formulas_notation()
        self.check_pq30_implementation_details()
        self.check_pq31_figures_described()
        self.check_pq32_all_warnings()
        self.check_pq33_limitations_included()
        self.check_pq34_historical_context()
        self.check_pq35_generic_test_pages()
        self.check_pq36_line_counts()
        self.check_pq37_extracted_from_predicate()
        self.check_pq38_form_contracts_exist()
        self.check_pq39_yaml_quotes()

        # === Post-ingest ===
        self.check_po42_blockid_regex_caret()
        self.check_po44_log_complete()
        self.check_po45_team_presentation_source()
        self.check_po46_page_depth_minimums()

        # === Wiki integrity (whole-vault invariants, audit T12) ===
        self.check_wi47_embed_resolution()
        self.check_wi48_duplicate_concepts()
        self.check_wi49_index_coverage()
        self.check_wi50_confidence_cap()
        self.check_wi51_log_entry_for_slug()

        # Manual checks fail unless explicitly acknowledged via --ack;
        # silent exclusion from the failure count is what let a broken
        # wiki audit 'PASS' before 2026-06-12.
        for check in self.checks:
            if check.manual and not check.passed:
                if check.id in self.ack:
                    check.ok("acknowledged by operator via --ack")
                else:
                    check.fail("manual verification not acknowledged — verify, then rerun with --ack " + check.id)

    # ------------------------------------------------------------------
    # Phase 1-2 checks
    # ------------------------------------------------------------------
    def check_ch01_splitting_attempted(self):
        check = self.add_check("CH-01", "Chapter splitting attempted 4 ways before fallback", "Phase 1-2", manual=True)
        if not self.log_file.exists():
            check.fail("log.md not found")
            return
        content = self.log_file.read_text()
        if self.slug in content and ("chapter detection" in content.lower() or "split" in content.lower()):
            check.ok("log.md references chapter splitting")
        else:
            check.warn("Cannot verify from log.md alone — check manually")

    def check_ch02_block_ids_annotated(self):
        check = self.add_check("CH-02", "Block IDs annotated in all chapter files", "Phase 1-2")
        if not self.chapters_dir.exists():
            check.fail(f"Chapters dir not found: {self.chapters_dir}")
            return
        files = list(self.chapters_dir.glob("*.md"))
        if not files:
            check.fail("No chapter files found")
            return
        missing = []
        for f in files:
            text = f.read_text()
            if not re.search(rf'\^{re.escape(self.slug)}-ch\d+-\d+', text):
                missing.append(f.name)
        if missing:
            check.fail(f"Missing block IDs in: {', '.join(missing[:5])}")
        else:
            check.ok(f"All {len(files)} chapter files have block IDs")

    def check_ch03_manifest_exists(self):
        check = self.add_check("CH-03", "Manifest generated during conversion", "Phase 1-2")
        manifest = self.wiki / "raw" / "papers" / self.slug / "manifest.json"
        if manifest.exists():
            check.ok(f"manifest.json exists ({manifest.stat().st_size} bytes)")
        else:
            check.fail("manifest.json not found")

    def check_ch04_no_stray_folders(self):
        check = self.add_check("CH-04", "No stray test/chunk folders in raw/papers/<slug>/", "Phase 1-2")
        slug_dir = self.wiki / "raw" / "papers" / self.slug
        if not slug_dir.exists():
            check.fail(f"Slug dir not found: {slug_dir}")
            return
        stray = []
        stray_prefixes = ("test", "chunk", "chapters-auto", "split-pdfs")
        for d in slug_dir.rglob("*"):
            if not d.is_dir() or "archive" in d.relative_to(slug_dir).parts:
                continue
            if d.name.startswith(stray_prefixes) and d.name != "pdf_chunks":
                stray.append(str(d.relative_to(slug_dir)))
        if stray:
            check.fail(f"Stray folders found: {', '.join(stray[:5])}")
        else:
            check.ok("No stray test/chunk/split debris folders")


    # ------------------------------------------------------------------
    # Phase 3 checks
    # ------------------------------------------------------------------
    def check_ex06_one_chapter_per_subagent(self):
        check = self.add_check("EX-06", "Every sub-agent processed ≤1 unit", "Phase 3", manual=True)
        check.warn("Verify via the Phase 3.3 dispatch plan and recorded dispatch-result.json (one task per unit/lane)")

    def check_ex08_toolsets_all(self):
        check = self.add_check("EX-08", "Runtime-neutral prompt-contract dispatch recorded for specialist lanes", "Phase 3")
        report_path = self.extractions_dir / "specialist-dispatch-report.json"
        if not report_path.exists():
            check.fail("specialist-dispatch-report.json not found")
            return
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"specialist-dispatch-report.json unreadable: {exc}")
            return
        mode = report.get("agent_mode")
        if mode != "runtime-neutral-prompt-contracts":
            check.fail(f"agent_mode is {mode!r}, expected 'runtime-neutral-prompt-contracts'")
            return
        check.ok("Dispatch report records runtime-neutral prompt-contract mode")

    def check_ex09_role_leaf(self):
        check = self.add_check("EX-09", "All specialist unit/lane pairs have recorded runtime job ids", "Phase 3", manual=True)
        check.warn("Verify Phase 3.3 gate PASS and one recorded runtime job id per unit/lane pair")

    def check_ex10_pydantic_validation(self):
        check = self.add_check("EX-10", "Pydantic validation passed on all extraction JSONs", "Phase 3")
        schema_script = self.wiki / "_meta" / "scripts" / "schemas" / "extraction_schema.py"
        if not schema_script.exists():
            check.fail("extraction_schema.py not found")
            return
        validation_marker = self.extractions_dir / "_validation_passed"
        schema_report = self.extractions_dir / "schema-validation-report.json"
        if not validation_marker.exists():
            check.fail("No Phase 3.4 validation marker found")
            return
        if not schema_report.exists():
            check.fail("schema-validation-report.json not found")
            return
        try:
            report = json.loads(schema_report.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"schema-validation-report.json unreadable: {exc}")
            return
        marker_text = validation_marker.read_text(encoding="utf-8", errors="replace")
        if "validated_by: library_phase34_verify.py" not in marker_text:
            check.fail("_validation_passed was not written by library_phase34_verify.py")
            return
        if report.get("status") != "PASS" or report.get("valid") != report.get("total") or int(report.get("total", 0)) == 0:
            check.fail("schema-validation-report.json is not a non-empty PASS")
            return
        check.ok(f"Phase 3.4 schema validation passed for {report.get('valid')} JSON files")

    def check_ex11_json_has_block_ids(self):
        check = self.add_check("EX-11", "All extraction JSONs contain block_id references", "Phase 3")
        if not self.extractions_dir.exists():
            check.fail("Extractions dir not found")
            return
        jsons = self.extraction_jsons()
        if not jsons:
            check.fail("No extraction schema JSONs found")
            return
        missing = []
        for j in jsons:
            try:
                data = json.loads(j.read_text())
            except (json.JSONDecodeError, IOError):
                continue
            items = []
            if isinstance(data, dict):
                for key in ["concepts", "entities", "formulas"]:
                    val = data.get(key, [])
                    if isinstance(val, dict):
                        items.extend(val.values())
                    elif isinstance(val, list):
                        items.extend(val)
            elif isinstance(data, list):
                items = data
            has_bid = any(
                item.get("block_ids") or item.get("block_id")
                for item in items if isinstance(item, dict)
            )
            declared_absent = isinstance(data, dict) and data.get("no_lane_content") is True
            if not has_bid and not declared_absent:
                missing.append(j.name)
        if missing:
            check.fail(f"Missing block IDs in: {', '.join(missing[:5])}")
        else:
            check.ok(f"All {len(jsons)} JSONs contain block_id references")

    def check_ex12_concept_density_fields(self):
        # Only `confidence` is required: the extraction schema defaults
        # concepts_per_100_lines and no worker contract asks for it.
        check = self.add_check("EX-12", "All concepts have a confidence field", "Phase 3")
        if not self.extractions_dir.exists():
            check.fail("Extractions dir not found")
            return
        jsons = self.extraction_jsons()
        missing = []
        for j in jsons:
            try:
                data = json.loads(j.read_text())
            except (json.JSONDecodeError, IOError):
                continue
            concepts = data.get("concepts", []) if isinstance(data, dict) else []
            for c in concepts:
                if "confidence" not in c:
                    missing.append(f"{j.name}:{c.get('slug', '?')}")
                    break
        if missing:
            check.fail(f"Missing fields in: {', '.join(missing[:5])}")
        else:
            check.ok("All concepts have required fields")

    def check_ex13_generic_test(self):
        check = self.add_check("EX-13", "Generic test passed on all definitions", "Phase 3", manual=True)
        check.warn("Requires semantic review — definitions must contain book-specific language")

    def check_ex14_no_regex_fallback(self):
        check = self.add_check("EX-14", "No regex keyword fallback was used", "Phase 3", manual=True)
        if self.log_file.exists():
            content = self.log_file.read_text()
            if "regex fallback" in content.lower() or "keyword fallback" in content.lower():
                check.fail("log.md indicates regex fallback was used")
                return
        check.ok("No evidence of regex fallback in logs")

    # ------------------------------------------------------------------
    # Phase 4 checks
    # ------------------------------------------------------------------
    def check_sc15_scoring_layer_used(self):
        check = self.add_check("SC-15", "Phase 4 scoring runner produced scored and candidate artifacts", "Phase 4")
        report_path = self.extractions_dir / "phase4-scoring-report.json"
        scored = self.extractions_dir / "master-scored.json"
        top = self._first_existing("master-top.json", "master-top56.json")
        clean = self._first_existing("master-top-clean.json", "master-top56-clean.json")
        candidates = self.extractions_dir / "concept-selection-candidates.md"
        missing = [p.name for p in [report_path, scored, top, clean, candidates] if not p.exists()]
        if missing:
            check.fail(f"Missing: {', '.join(missing)}")
            return
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"phase4-scoring-report.json unreadable: {exc}")
            return
        if report.get("status") not in {"AWAITING_USER_CONFIRMATION", "PASS"} or int(report.get("candidate_count", 0)) <= 0:
            check.fail("phase4-scoring-report.json has no usable candidates")
        else:
            check.ok(f"Phase 4 scoring produced {report.get('candidate_count')} candidates")

    def check_sc16_user_confirmed(self):
        check = self.add_check("SC-16", "User confirmed concept selection", "Phase 4")
        confirmation = self.extractions_dir / "phase4-confirmation.json"
        gate = self.extractions_dir / "gates" / "phase-4.json"
        if not confirmation.exists() or not gate.exists():
            check.fail("Phase 4 confirmation or PASS gate missing")
            return
        try:
            conf = json.loads(confirmation.read_text())
            gate_data = json.loads(gate.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"Phase 4 confirmation/gate unreadable: {exc}")
            return
        if conf.get("status") != "PASS" or gate_data.get("status") != "PASS" or int(conf.get("selected_count", 0)) <= 0:
            check.fail("Phase 4 has not recorded a non-empty user-confirmed PASS")
        else:
            check.ok(f"User confirmed {conf.get('selected_count')} concepts")

    def check_sc17_blockid_validator_passed(self):
        check = self.add_check("SC-17", "Block-ID resolvability check passed", "Phase 4")
        marker = self.extractions_dir / "_blockid_valid"
        report_path = self.extractions_dir / "blockid-validation-report.json"
        if not marker.exists() or not report_path.exists():
            check.fail("_blockid_valid marker or blockid-validation-report.json missing")
            return
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"blockid-validation-report.json unreadable: {exc}")
            return
        marker_text = marker.read_text(encoding="utf-8", errors="replace")
        if "validated_by: blockid_validator.py" not in marker_text:
            check.fail("_blockid_valid was not written by the canonical validator")
        elif report.get("valid") is not True or int(report.get("referenced_block_ids", 0)) <= 0:
            check.fail("blockid-validation-report.json is not a non-empty PASS")
        else:
            check.ok(f"Block-ID validation passed for {report.get('referenced_block_ids')} referenced IDs")

    def check_sc18_no_dead_block_ids(self):
        check = self.add_check("SC-18", "No dead block IDs remain in extraction data", "Phase 4")
        report_path = self.extractions_dir / "blockid-validation-report.json"
        if not report_path.exists():
            check.fail("blockid-validation-report.json not found")
            return
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"blockid-validation-report.json unreadable: {exc}")
            return
        if int(report.get("missing_count", 0)) != 0:
            check.fail(f"Dead block IDs remain: {report.get('missing_count')}")
        else:
            check.ok("No dead block IDs in Phase 4 validation report")

    def check_sc19_latex_slugs_filtered(self):
        check = self.add_check("SC-19", "LaTeX artifact slugs filtered before presenting top-N list", "Phase 4")
        clean = self._first_existing("master-top-clean.json", "master-top56-clean.json")
        if not clean.exists():
            check.fail("master-top-clean.json not found")
            return
        try:
            data = json.loads(clean.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"{clean.name} unreadable: {exc}")
            return
        if "_latex_filtered" not in data:
            check.fail(f"{clean.name} lacks _latex_filtered evidence")
        else:
            check.ok(f"LaTeX filter ran; removed {data['_latex_filtered'].get('removed_count', 0)} slugs")

    def check_sc20_template_engine_used(self):
        check = self.add_check("SC-20", "Canonical Phase 5 page writer used", "Phase 4-5")
        report_path = self.extractions_dir / "page-build-report.json"
        gate_path = self.extractions_dir / "gates" / "phase-5.json"
        if not report_path.exists() or not gate_path.exists():
            check.fail("page-build-report.json or phase-5 gate missing")
            return
        try:
            report = json.loads(report_path.read_text())
            gate = json.loads(gate_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"Phase 5 report/gate unreadable: {exc}")
            return
        if report.get("generated_by") != "library_phase5_pages.py" or report.get("status") != "PASS" or gate.get("status") != "PASS":
            check.fail("Phase 5 was not completed by library_phase5_pages.py with PASS gate")
        elif int(report.get("pages_written", 0)) <= 0:
            check.fail("Phase 5 report wrote zero pages")
        else:
            check.ok(f"Canonical Phase 5 writer created {report.get('pages_written')} pages")

    def check_sc21_yaml_serializer_used(self):
        check = self.add_check("SC-21", "YAML serializer-compatible frontmatter on all pages", "Phase 5")
        report_path = self.extractions_dir / "page-build-report.json"
        if not report_path.exists():
            check.fail("page-build-report.json not found")
            return
        bad_yaml = []
        required_order = ["title", "created", "updated", "confidence", "last_reinforced", "tier", "quality", "quality_notes", "scope", "author"]
        for p in self.all_pages:
            text = p.read_text()
            if not text.startswith("---"):
                bad_yaml.append(f"{p.name}: missing frontmatter")
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                bad_yaml.append(f"{p.name}: malformed frontmatter")
                continue
            keys = [line.split(":", 1)[0].strip() for line in parts[1].splitlines() if ":" in line]
            if keys[:len(required_order)] != required_order:
                bad_yaml.append(f"{p.name}: frontmatter order/keys mismatch")
        if bad_yaml:
            check.fail(f"; ".join(bad_yaml[:5]))
        else:
            check.ok("All generated pages have deterministic YAML frontmatter")

    def check_sc22_no_yaml_errors(self):
        check = self.add_check("SC-22", "No YAML parsing errors in any page", "Phase 5")
        try:
            import yaml
        except ImportError:
            check.warn("PyYAML not installed — skipping deep YAML validation")
            return
        errors = []
        for p in self.all_pages:
            text = p.read_text()
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    try:
                        yaml.safe_load(parts[1])
                    except yaml.YAMLError as e:
                        errors.append(f"{p.name}: {e}")
        if errors:
            check.fail(f"YAML errors in: {', '.join(errors[:5])}")
        else:
            check.ok("No YAML parsing errors")

    # ------------------------------------------------------------------
    # Page Quality checks
    # ------------------------------------------------------------------
    def check_pq23_block_embeds(self):
        check = self.add_check("PQ-23", "Every concept page has ≥2 block embeds ![[source#^id]]", "Page Quality")
        failures = []
        for p in self.concept_files:
            text = p.read_text()
            embeds = re.findall(r'!\[\[[^\]]+#\^[^\]]+\]\]', text)
            if len(embeds) < 2:
                failures.append(f"{p.name}: {len(embeds)} embeds")
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok(f"All {len(self.concept_files)} concept pages have ≥2 block embeds")

    def check_pq24_authors_words_section(self):
        check = self.add_check("PQ-24", "Every concept page has ## Author's Words section with verbatim quotes", "Page Quality")
        failures = []
        for p in self.concept_files:
            text = p.read_text()
            if not re.search(r'^##\s*Author\'s\s*Words', text, re.MULTILINE | re.IGNORECASE):
                failures.append(p.name)
        if failures:
            check.fail(f"Missing section in: {', '.join(failures[:5])}")
        else:
            check.ok("All concept pages have Author's Words section")

    def check_pq27_exact_terminology(self):
        check = self.add_check("PQ-27", "Every concept page uses author's exact terminology", "Page Quality", manual=True)
        check.warn("Requires comparison against source text — verify manually")

    def check_pq28_specific_examples(self):
        check = self.add_check("PQ-28", "Every concept page has a source-grounded specific example", "Page Quality")
        failures = []
        for p in self.concept_files:
            text = p.read_text()
            m = re.search(r'^##\s*Specific\s*Example.*?(?=^##|\Z)', text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if not m:
                failures.append(f"{p.name}: no Specific Example section")
                continue
            if not re.search(rf'\^{re.escape(self.slug)}-ch\d+-\d+', m.group(0)):
                failures.append(f"{p.name}: example lacks source evidence")
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok("All concept pages have specific examples")

    def check_pq29_formulas_notation(self):
        check = self.add_check("PQ-29", "Formulas use author's exact notation and variable definitions", "Page Quality", manual=True)
        check.warn("Requires comparison against source text — verify manually")

    def check_pq30_implementation_details(self):
        check = self.add_check("PQ-30", "Implementation details included if author provides code/pseudocode", "Page Quality", manual=True)
        check.warn("Verify manually against source text")

    def check_pq31_figures_described(self):
        check = self.add_check("PQ-31", "Figures and diagrams described if present in book", "Page Quality", manual=True)
        check.warn("Verify manually against source text")

    def check_pq32_all_warnings(self):
        check = self.add_check("PQ-32", "ALL author warnings included in ## Author's Warnings", "Page Quality", manual=True)
        check.warn("Verify manually against the warnings lane output (domain-warnings.md)")

    def check_pq33_limitations_included(self):
        check = self.add_check("PQ-33", "Author's limitations and counter-arguments included", "Page Quality", manual=True)
        check.warn("Verify manually against source text")

    def check_pq34_historical_context(self):
        check = self.add_check("PQ-34", "Historical/empirical context included if author provides it", "Page Quality", manual=True)
        check.warn("Verify manually against source text")

    def check_pq35_generic_test_pages(self):
        check = self.add_check("PQ-35", "No paragraph could appear unchanged on Wikipedia", "Page Quality", manual=True)
        check.warn("Requires semantic review — verify manually")

    def check_pq36_line_counts(self):
        check = self.add_check("PQ-36", "Concept page depth ≥80 lines", "Page Quality")
        failures = []
        for p in self.concept_files:
            lines = p.read_text().splitlines()
            if len(lines) < 80:
                failures.append(f"{p.name}: {len(lines)} lines (<80)")
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok(f"Line count requirements met ({len(self.concept_files)} concepts)")

    def check_pq37_extracted_from_predicate(self):
        check = self.add_check("PQ-37", "extracted_from:: used on all new pages (not derived_from)", "Page Quality")
        failures = []
        for p in self.all_pages:
            text = p.read_text()
            if "extracted_from::" not in text:
                failures.append(f"{p.name}: missing extracted_from")
            if "derived_from::" in text and self.slug in text:
                failures.append(f"{p.name}: uses derived_for newly extracted page")
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok("All pages use extracted_from")

    def check_pq38_form_contracts_exist(self):
        check = self.add_check("PQ-38", "Form contracts exist and are referenced correctly", "Page Quality")
        concept_contract = self.wiki / "_meta" / "contracts" / "concept-form-contract.md"
        missing = []
        if not concept_contract.exists(): missing.append("concept-form-contract.md")
        if missing:
            check.fail(f"Missing contracts: {', '.join(missing)}")
        else:
            check.ok("Concept form contract exists")

    def check_pq39_yaml_quotes(self):
        check = self.add_check("PQ-39", "YAML frontmatter titles quoted if containing colons or hashes", "Page Quality")
        failures = []
        for p in self.all_pages:
            text = p.read_text()
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter = parts[1]
            # Check for unquoted colons or hashes in YAML values
            for line in frontmatter.splitlines():
                # This check is specifically about title scalars; other controlled
                # vocabulary fields such as tier/status are valid unquoted YAML.
                if not line.strip().startswith("title:"):
                    continue
                if ":" in line and not re.search(r':\s*["\']', line):
                    failures.append(f"{p.name}: potentially unquoted YAML: {line.strip()[:60]}")
                    break
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok("YAML frontmatter appears properly quoted")

    # ------------------------------------------------------------------
    # Post-ingest checks
    # ------------------------------------------------------------------


    def check_po42_blockid_regex_caret(self):
        check = self.add_check("PO-42", "Block-ID validator regex uses capturing group (excludes ^ prefix)", "Post-Ingest")
        validator = self.wiki / "_meta" / "scripts" / "blockid_validator.py"
        if not validator.exists():
            check.fail("blockid_validator.py not found")
            return
        text = validator.read_text()
        if r'\^(' in text or r"\^(" in text:
            check.ok("Validator uses capturing group to strip caret")
        elif r'\^' in text:
            check.fail("Validator matches caret but may not strip it — verify regex")
        else:
            check.warn("Cannot determine caret handling from source")


    def check_po44_log_complete(self):
        check = self.add_check("PO-44", "log.md documents all steps including failures and fallback usage", "Post-Ingest")
        if not self.log_file.exists():
            check.fail("log.md not found")
            return
        content = self.log_file.read_text()
        # Check for recent entries mentioning this slug
        if self.slug in content:
            check.ok("log.md contains entries for this slug")
        else:
            check.fail("log.md has no entries for this slug")

    def check_po45_team_presentation_source(self):
        check = self.add_check("PO-45", "Team presentations were assembled and validated before page creation", "Post-Ingest")
        report_path = self.extractions_dir / "presentation-report.json"
        if not report_path.exists():
            check.fail("presentation-report.json not found")
            return
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, IOError) as exc:
            check.fail(f"presentation-report.json unreadable: {exc}")
            return
        if report.get("status") != "PASS" or int(report.get("checked", 0)) == 0:
            check.fail("presentation-report.json is not a non-empty PASS")
            return
        missing = []
        for row in report.get("presentations", []):
            path_value = row.get("presentation")
            if not path_value or not (self.wiki / path_value).exists():
                missing.append(str(path_value))
        if missing:
            check.fail(f"Presentation files missing: {', '.join(missing[:5])}")
        else:
            check.ok(f"Phase 3.5 validated {report.get('checked')} team presentations")

    def check_po46_page_depth_minimums(self):
        check = self.add_check("PO-46", "No concept page under 80 lines or lacking block embeds, verbatim quotes, and specific examples", "Post-Ingest")
        failures = []
        for p in self.concept_files:
            text = p.read_text()
            lines = text.splitlines()
            if len(lines) < 80:
                failures.append(f"{p.name}: {len(lines)} lines (<80)")
                continue
            embeds = len(re.findall(r'!\[\[[^\]]+#\^[^\]]+\]\]', text))
            if embeds < 2:
                failures.append(f"{p.name}: {embeds} embeds (<2)")
                continue
            quotes = [l for l in lines if l.strip().startswith(">") and len(l.strip()) > 10]
            if len(quotes) < 2:
                failures.append(f"{p.name}: {len(quotes)} substantial quotes (<2)")
        if failures:
            check.fail(f"; ".join(failures[:5]))
        else:
            check.ok("All concept pages meet minimum depth requirements")

    # ------------------------------------------------------------------
    # Wiki integrity checks (whole-vault invariants)
    # ------------------------------------------------------------------
    def check_wi47_embed_resolution(self):
        check = self.add_check("WI-47", "Every block embed/link in concepts/ resolves in the vault", "Wiki Integrity")
        pages = sorted(self.concepts_dir.glob("*.md")) if self.concepts_dir.exists() else []
        if not pages:
            check.fail("no concept pages found")
            return
        index = wiki_integrity.build_vault_index(self.wiki)
        report = wiki_integrity.check_files(index, pages)
        if report["dead_links"]:
            samples = []
            for row in report["files"]:
                samples.extend(f"{row['file']}: {f['raw']} [{f['status']}]" for f in row["dead_findings"][:2])
            check.fail(f"{report['dead_links']} dead links in {report['files_with_dead_links']} pages; e.g. {'; '.join(samples[:5])}")
        else:
            check.ok(f"{report['links_checked']} block links across {report['files_checked']} pages all resolve")

    def check_wi48_duplicate_concepts(self):
        check = self.add_check("WI-48", "No two concept pages normalize to the same concept slug", "Wiki Integrity")
        stems: Dict[str, List[str]] = {}
        for p in sorted(self.concepts_dir.glob("*.md")):
            stems.setdefault(scoring_layer.normalize_slug(p.stem), []).append(p.stem)
        dupes = {k: v for k, v in stems.items() if len(v) > 1}
        if dupes:
            check.fail(f"duplicate concepts: {sorted(dupes.values())[:5]}")
        else:
            check.ok(f"{len(stems)} concept pages, all normalized slugs unique")

    def check_wi49_index_coverage(self):
        check = self.add_check("WI-49", "index.md lists every concept page", "Wiki Integrity")
        if not self.index_file.exists():
            check.fail("index.md not found")
            return
        indexed = set(re.findall(r"\[\[([^\]|#]+)\]\]", self.index_file.read_text(encoding="utf-8", errors="replace")))
        stems = {p.stem for p in self.concepts_dir.glob("*.md")}
        missing = sorted(stems - indexed)
        stale = sorted(s for s in indexed - stems if not (self.wiki / "_archive" / f"{s}.md").exists() and s not in {"concept-form-contract"})
        if missing:
            check.fail(f"{len(missing)} concept pages missing from index.md: {missing[:5]}")
        elif stale:
            check.warn(f"index.md links without live pages: {stale[:5]}")
            check.ok(f"all {len(stems)} concept pages indexed ({len(stale)} stale links noted)")
        else:
            check.ok(f"all {len(stems)} concept pages indexed")

    def check_wi50_confidence_cap(self):
        check = self.add_check("WI-50", "Frontmatter confidence <= 0.95 on every concept page (never absolute)", "Wiki Integrity")
        over = []
        for p in sorted(self.concepts_dir.glob("*.md")):
            m = re.search(r"^confidence:\s*([0-9.]+)", p.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            if m and float(m.group(1)) > 0.95:
                over.append(f"{p.name}={m.group(1)}")
        if over:
            check.fail(f"confidence cap violations: {over[:8]}")
        else:
            check.ok("no concept page exceeds the 0.95 confidence cap")

    def check_wi51_log_entry_for_slug(self):
        check = self.add_check("WI-51", "log.md has a contract-format entry for this slug", "Wiki Integrity")
        if not self.log_file.exists():
            check.fail("log.md not found")
            return
        text = self.log_file.read_text(encoding="utf-8", errors="replace")
        entries = [line for line in text.splitlines() if line.startswith("## [") and self.slug in line]
        if entries:
            check.ok(f"{len(entries)} contract-format log entries reference {self.slug}")
        else:
            check.fail(f"no `## [timestamp] action | subject | actor` log entry mentions {self.slug}")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def generate_report(self) -> Dict:
        passed = sum(1 for c in self.checks if c.passed)
        failed = sum(1 for c in self.checks if not c.passed)
        manual = sum(1 for c in self.checks if c.manual)
        total = len(self.checks)

        return {
            "slug": self.slug,
            "wiki": ".",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "total_checks": total,
                "passed": passed,
                "failed": failed,
                "manual_verification_required": manual,
                "acknowledged": sorted(self.ack),
            },
            "checks": [c.to_dict() for c in self.checks],
            "overall_pass": failed == 0
        }

    def write_report(self):
        report = self.generate_report()
        write_json(self.report, report)
        return report

    def print_summary(self, report: Dict):
        s = report["summary"]
        print("=" * 60)
        print(f"Domain Library Audit Report: {self.slug}")
        print("=" * 60)
        print(f"Total checks: {s['total_checks']}")
        print(f"Passed:       {s['passed']}")
        print(f"Failed:       {s['failed']}")
        print(f"Manual:       {s['manual_verification_required']}")
        print("=" * 60)

        if s["failed"] > 0:
            print("\nFAILED CHECKS:")
            for c in report["checks"]:
                if not c["passed"]:
                    print(f"  [{c['id']}] {c['description']}")
                    for e in c["errors"]:
                        print(f"      ❌ {e}")

        if s["manual_verification_required"] > 0:
            print("\nMANUAL VERIFICATION REQUIRED:")
            for c in report["checks"]:
                if c["manual"]:
                    status = "✅" if c["passed"] else "⚠️"
                    print(f"  [{c['id']}] {status} {c['description']}")
                    for d in c.get("details", []):
                        print(f"      {d}")

        print(f"\nFull report: {self.report}")
        print(f"Exit code: {0 if report.get('overall_pass', s['failed'] == 0) else 1}")


def run_grounding(wiki: Path, slug: str) -> dict[str, Any]:
    chapters = wiki / "raw" / "papers" / slug / "chapters"
    out = wiki / "_meta" / "extractions" / slug
    lex = source_grounding_quality.lexical_report(wiki, slug, chapters, 0.12)
    img = source_grounding_quality.image_coverage(wiki, slug, chapters, wiki / "raw" / "papers" / slug / "image-refs-report.json")
    write_json(out / "lexical-overlap-report.json", lex)
    write_json(out / "image-to-page-coverage.json", img)
    source_grounding_quality.write_lexical_md(lex, out / "lexical-overlap-report.md")
    source_grounding_quality.write_image_md(img, out / "image-to-page-coverage.md")
    return {"status": "PASS" if lex["pages_checked"] > 0 and lex["low_overlap_count"] == 0 else "FAIL", "lexical": lex, "images": img}


def finalize_state(wiki: Path, slug: str, audit_pass: bool, grounding_pass: bool, report: Path) -> bool:
    if not audit_pass or not grounding_pass:
        return False
    state = load_state(wiki, slug)
    if state.get("status") != "READY_FOR_POST":
        raise RuntimeError(f"cannot finalize state {state.get('status')!r}; expected READY_FOR_POST")
    gates = {str(k): str(v) for k, v in state.get("gates", {}).items()}
    gate = write_gate(wiki, slug, "post", "PASS", {"audit_report": rel(report, wiki), "grounding_report": rel(wiki / "_meta" / "extractions" / slug / "lexical-overlap-report.json", wiki)})
    gates["post"] = rel(gate, wiki)
    completed = [str(value) for value in state.get("completed_phases", [])]
    if "post" not in completed:
        completed.append("post")
    write_state(wiki, slug, "DONE", "post", completed, gates, runner="library_audit.py")
    return True


def main():
    parser = argparse.ArgumentParser(description="Domain Library Ingest Audit")
    parser.add_argument("--slug", required=True, help="Source slug (e.g., example-book)")
    parser.add_argument("--wiki", required=True, help="Path to Domain Library wiki root")
    parser.add_argument("--report", required=True, help="Path to write JSON report")
    parser.add_argument(
        "--ack",
        default="",
        help="Comma-separated manual check IDs the operator has verified by hand (e.g. CH-01,PQ-27). Unacknowledged manual checks FAIL the audit.",
    )
    args = parser.parse_args()

    ack = {item.strip() for item in args.ack.split(",") if item.strip()}
    args.slug = validate_slug(args.slug)
    audit = LibraryAudit(args.slug, Path(args.wiki), Path(args.report), ack=ack)
    wiki = Path(args.wiki).resolve()
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = wiki / report_path
    audit.report = report_path
    try:
        grounding = run_grounding(wiki, args.slug)
    except Exception as exc:
        grounding = {"status": "FAIL", "error": str(exc)}
    audit.run_all()
    report = audit.write_report()
    report["grounding"] = grounding
    report["overall_pass"] = report["overall_pass"] and grounding["status"] == "PASS"
    write_json(report_path, report)
    audit.print_summary(report)
    finalize_state(wiki, args.slug, report["overall_pass"], grounding["status"] == "PASS", report_path)

    sys.exit(0 if report["overall_pass"] else 1)


if __name__ == "__main__":
    main()
