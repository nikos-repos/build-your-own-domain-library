# Contributing

Keep changes small and prove the user-visible behavior they protect.

1. Work in Git; do not create `.orig` snapshots in the repository.
2. Never edit pipeline gates, state, validation markers, `index.md`, or
   generated extraction outputs by hand.
3. For behavior or contract changes, add one regression that fails without
   the change.
4. When behavior changes, update the runner, its regression, the ingest-skill
   command row, the matching gate/runbook text, and the flowchart in the same
   commit.
5. Run the checks below before requesting review.

```bash
python3 -m py_compile _meta/scripts/*.py
domain-library run library_pipeline_test_suite
bash _meta/scripts/docs_drift_check.sh .
```

Changes to page contracts, evidence rules, gate conditions, dependency files,
or guard defaults require explicit owner approval. Guard flags such as
`--force`, `--apply`, and duplicate overrides remain opt-in operator actions.
