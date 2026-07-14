#!/usr/bin/env python3
"""
Pydantic Schema Validation for Domain Library Sub-Agent Extractions
====================================================================
Validates sub-agent JSON output before it enters the merge pipeline.
Rejects malformed extractions immediately, preventing bad data from
poisoning the merge.

Usage:
    python3 _meta/schemas/extraction_schema.py validate \
        --input _meta/extractions/<slug>/ch-01.json \
        --slug example-public-domain-book

    python3 _meta/schemas/extraction_schema.py validate-batch \
        --dir _meta/extractions/<slug>/ \
        --slug example-public-domain-book
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field, field_validator, ValidationError


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

BLOCK_ID_PATTERN = r"^[a-z0-9-]+-ch\d+-\d+$"


class Definition(BaseModel):
    chapter: int
    chapter_title: str
    definition: str = Field(..., min_length=10)
    block_id: str = Field(..., pattern=BLOCK_ID_PATTERN)


class Formula(BaseModel):
    name: str
    expression: str = Field(..., min_length=3)
    block_id: str = Field(..., pattern=BLOCK_ID_PATTERN)
    context: str = ""


class Claim(BaseModel):
    text: str = Field(..., min_length=10)
    block_id: str = Field(..., pattern=BLOCK_ID_PATTERN)
    confidence_marker: str = Field(..., pattern=r"^(authoritative|tentative|opinion)$")


class EntityMention(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9-]+$")
    name: str
    role: str
    mentions: List[str] = Field(default_factory=list)


class Concept(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9-]+$", min_length=3)
    name: str = Field(..., min_length=3)
    definitions: List[Definition] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    formulas: List[Formula] = Field(default_factory=list)
    block_ids: List[str] = Field(default_factory=list)
    cross_references: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    concepts_per_100_lines: float = Field(default=0.0, ge=0.0)
    chapters: List[int] = Field(default_factory=list)

    @field_validator("definitions")
    @classmethod
    def must_have_at_least_one_definition(cls, v: List[Definition]) -> List[Definition]:
        if len(v) == 0:
            raise ValueError("Concept must have at least one definition")
        return v


class ExtractionOutput(BaseModel):
    source: str = Field(..., pattern=r"^[a-z0-9-]+$", min_length=3)
    chapter: int = Field(..., ge=1)
    chapter_title: str = Field(..., min_length=3)
    extracted_at: str
    concepts: List[Concept] = Field(default_factory=list)
    entities: List[EntityMention] = Field(default_factory=list)
    formulas: List[Formula] = Field(default_factory=list)
    claims: List[Claim] = Field(default_factory=list)

    @field_validator("concepts")
    @classmethod
    def must_have_concepts(cls, v: List[Concept]) -> List[Concept]:
        if len(v) == 0:
            raise ValueError("Extraction must contain at least one concept")
        return v


# ---------------------------------------------------------------------------
# Block-ID Pattern Validator (runtime slug injection)
# ---------------------------------------------------------------------------

class BlockIdValidator:
    def __init__(self, slug: str):
        self.slug = slug
        self.pattern = re.compile(rf"^{re.escape(slug)}-ch\d+-\d+$")

    def validate(self, block_id: str) -> bool:
        return bool(self.pattern.match(block_id))

    def validate_list(self, block_ids: List[str]) -> List[str]:
        invalid = [bid for bid in block_ids if not self.validate(bid)]
        return invalid


# ---------------------------------------------------------------------------
# Validation Functions
# ---------------------------------------------------------------------------

def collect_block_ids(extraction: ExtractionOutput) -> List[str]:
    """Collect all block IDs referenced in an extraction."""
    block_ids: List[str] = []
    for concept in extraction.concepts:
        block_ids.extend(concept.block_ids)
        for definition in concept.definitions:
            block_ids.append(definition.block_id)
        for formula in concept.formulas:
            block_ids.append(formula.block_id)
    for formula in extraction.formulas:
        block_ids.append(formula.block_id)
    for claim in extraction.claims:
        block_ids.append(claim.block_id)
    return block_ids


def validate_extraction_file(path: Path, slug: str) -> dict:
    """Validate a single extraction JSON file."""
    result = {
        "file": str(path),
        "valid": False,
        "pydantic_errors": [],
        "block_id_errors": [],
        "generic_test_failures": [],
        "stats": {}
    }

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result["pydantic_errors"].append(f"Invalid JSON: {e}")
        return result

    # Pydantic validation
    try:
        extraction = ExtractionOutput.model_validate(data)
        result["stats"] = {
            "concepts": len(extraction.concepts),
            "entities": len(extraction.entities),
            "formulas": len(extraction.formulas),
            "claims": len(extraction.claims)
        }
    except ValidationError as e:
        result["pydantic_errors"] = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        return result

    # Block-ID validation (slug-specific; Pydantic enforces generic format)
    bid_validator = BlockIdValidator(slug)
    invalid_bids = bid_validator.validate_list(list(set(collect_block_ids(extraction))))
    if invalid_bids:
        result["block_id_errors"] = invalid_bids[:20]  # cap at 20

    # Generic test: definitions must be specific (not Wikipedia-ready)
    for concept in extraction.concepts:
        for d in concept.definitions:
            if len(d.definition) < 30:
                result["generic_test_failures"].append(
                    f"{concept.slug}: definition too short ({len(d.definition)} chars)"
                )

    if result["generic_test_failures"]:
        result["generic_test_failures"] = result["generic_test_failures"][:20]

    result["valid"] = (
        len(result["pydantic_errors"]) == 0
        and len(result["block_id_errors"]) == 0
        and len(result["generic_test_failures"]) == 0
    )
    return result


def validate_batch(directory: Path, slug: str) -> List[dict]:
    """Validate all JSON files in a directory."""
    results = []
    for json_file in sorted(directory.glob("*.json")):
        if json_file.name.startswith("_"):
            continue
        results.append(validate_extraction_file(json_file, slug))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Validate extraction JSON against Pydantic schema")
    parser.add_argument("--slug", required=True, help="Source slug for block-id pattern validation")
    subparsers = parser.add_subparsers(dest="command")

    p_single = subparsers.add_parser("validate", help="Validate a single file")
    p_single.add_argument("--input", required=True, help="Path to JSON file")

    p_batch = subparsers.add_parser("validate-batch", help="Validate all JSON files in directory")
    p_batch.add_argument("--dir", required=True, help="Directory containing JSON files")

    args = parser.parse_args()

    if args.command == "validate":
        result = validate_extraction_file(Path(args.input), args.slug)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    elif args.command == "validate-batch":
        results = validate_batch(Path(args.dir), args.slug)
        valid_count = sum(1 for r in results if r["valid"])
        print(json.dumps({
            "total": len(results),
            "valid": valid_count,
            "invalid": len(results) - valid_count,
            "details": results
        }, indent=2))
        sys.exit(0 if valid_count == len(results) else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
