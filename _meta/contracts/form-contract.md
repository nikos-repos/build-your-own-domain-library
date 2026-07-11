---
title: form-contract
created: 2026-04-23
updated: 2026-04-23
confidence: 1.0
tier: procedural
quality: 0.9
scope: shared
author: orchestrator
---

- conforms_to::[[form-contract]]
- has_status::[[evergreen]]
- in_domain::[[meta]]

# Form Contract (Base)

This is the meta-contract that all other form contracts conform to.

## Purpose

Form contracts define the structural specification for each node kind in the wiki.
A node's `- conforms_to::[[<type>-form-contract]]` predicate asserts that the node
meets that specification.

## Required Elements (Every Form Contract)

1. **Required classification predicates** — `conforms_to::`, `has_status::`, `in_domain::`
2. **Required Relations** — minimum provenance predicates
3. **Body structure** — expected sections and their order
4. **Rules** — constraints specific to this node kind
5. **Example** — one worked example page

## Available Form Contracts

- [[concept-form-contract]] — strategies, methods, models, metrics
- [[comparison-form-contract]] — side-by-side analyses
- [[query-form-contract]] — filed query results
- [[workflow-form-contract]] — playbooks, checklists, decision trees
- [[crystallization-form-contract]] — completed research threads
