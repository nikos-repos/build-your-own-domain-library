# Failure Modes

## Specialist dispatch failures

| Symptom                           | Action                                                                                                                                |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Worker completes but file missing | Treat as failure; verifier must open correction                                                                                       |
| Worker writes no block IDs        | Re-run with stricter prompt or block for source issue                                                     |
| Worker reads wrong path           | Use shared workspace `dir:$WIKI_PATH`; paths relative to wiki root                                                                    |
| Duplicate specialist work         | Idempotency keys prevent duplicates; if duplicates exist, archive extras                                                              |
| Unit collision                    | Fix `unit_id` discovery; do not use `team-chapterNN` for parts                                                                        |
| Agent profile drift               | `library_phase33_dispatch.py --prepare` must fail if the global `_meta/agents/<lane>.md` profile is missing, malformed, or mismatched |
| Vision hallucination              | Keep marker/log unresolvable; never fabricate image content                                                                           |

## Direct API extraction trap

Direct one-shot LLM extraction is not a pipeline fallback. Any such attempt should be blocked. Should such an output make it through, output must be marked `thin_output: true` and fail normal quality gates unless explicitly accepted by the user.
