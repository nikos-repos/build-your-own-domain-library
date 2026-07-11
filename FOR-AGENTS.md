# Agent-guided set-up entry point

1. Never edit pipeline state, gates, or validation markers manually.
2. Read `README.md` and `_meta/config/domain.json`.
3. Ask user all of their domain-specific information and adjust all required files according to their answers.
4. Ask user to configure API keys in .env
5. Run `python library.py doctor`.
6. Instruct the user that domain-library is ready and they can begin by dropping a file in the raw/dropbox.

The workflow and stop conditions are in [the ingest operating skill](agents/skills/domain-library-ingest-pipeline/SKILL.md).


