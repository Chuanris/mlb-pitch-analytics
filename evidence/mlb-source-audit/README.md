# MLB source-audit evidence

This directory stores compact, reviewable manifests generated from the local DuckDB database and live official MLB schedule and game-feed responses. Raw API payloads, Parquet files, and the database remain local and ignored.

Regenerate the dated manifest from the repository root:

```powershell
.\.venv\Scripts\python.exe -m src.build_mlb_source_audit `
  --start-date 2026-09-09 `
  --end-date 2026-09-20 `
  --output evidence/mlb-source-audit/2026-09-09_2026-09-20.json
```

The command is read-only against DuckDB. It returns `0` only when every date reconciles, `1` when evidence is incomplete, and `2` when any date has an error. It still writes the manifest for non-passing audits so failures remain inspectable.

The manifest records response hashes, not full MLB responses. A hash shows which payload was observed at check time; it does not make the upstream immutable or prove that MLB is independently correct.
