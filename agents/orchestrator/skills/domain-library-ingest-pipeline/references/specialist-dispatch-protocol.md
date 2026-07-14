# Phase 3.3 runtime-neutral dispatch

1. Run `python3 _meta/scripts/library_phase33_dispatch.py --slug "$SLUG" --prepare`.
2. Treat `specialist-dispatch-plan.json` and its generated assignment files as the source of truth.
3. For every task, load the named prompt contract from `_meta/agents/`, use the current operator's native subagent mechanism, and require both `markdown_output` and `schema_output`.
4. Write `_meta/extractions/$SLUG/dispatch-result.json` in either supported shape:

```json
{
  "slug": "example-book",
  "tasks": [
    {
      "id": "DefsCh01",
      "runtime_task_id": "native-task-123",
      "job_id": "job-456",
      "runtime": "operator-runtime",
      "model": "provider/model"
    }
  ]
}
```

`results` may replace `tasks`; `run_id`, `task_id`, `launcher`, and `model_id` are normalized aliases. Planned IDs and obvious fake/mock/test identifiers are rejected.

5. Run `python3 _meta/scripts/library_phase33_dispatch.py --slug "$SLUG" --record --dispatch-result _meta/extractions/$SLUG/dispatch-result.json`.

Stop if any planned task, metadata field, or expected output is missing. Do not edit gates or state manually.
