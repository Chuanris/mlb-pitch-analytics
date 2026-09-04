# Security and repository hygiene

This project does not require a private API key for its documented data pipeline. MLB and Baseball Savant data are fetched through public endpoints used by the project dependencies.

## Before committing

- Keep local environment files in `.env`; only placeholder values belong in `.env.example`.
- Never commit access tokens, passwords, private keys, browser profiles, cookies, or credential exports.
- Generated Statcast partitions, DuckDB databases, model artifacts, exports, logs, dashboard bundles, virtual environments, and dependency folders are excluded by `.gitignore` and can be recreated from the documented pipeline.
- The reviewed dashboard snapshot at `dashboard/src/data.json` contains public baseball data used to reproduce the authored dashboard; it contains no application credentials.

If a secret is committed accidentally, revoke or rotate it first, then remove it from the complete Git history before publishing again.
