# Security and repository hygiene

This project does not require a private API key for its documented data pipeline. MLB and Baseball Savant data are fetched through public endpoints used by the project dependencies.

## Before committing

- Keep local environment files in `.env`; only placeholder values belong in `.env.example`.
- Never commit access tokens, passwords, private keys, browser profiles, cookies, or credential exports.
- Google Cloud deployment uses GitHub Workload Identity Federation and short-lived credentials. Do not add a service-account JSON key as a shortcut; `gha-creds-*.json`, Terraform state, and plan files are ignored because they can contain sensitive infrastructure metadata.
- The Workload Identity Provider must remain restricted to the configured repository and `main` branch. Use the protected `gcp-dev` GitHub environment for live plan/apply approval.
- The included Airflow Compose stack is localhost-only development infrastructure. Its Simple Auth Manager all-admin setting and fallback database/JWT values are not production credentials; replace the local values and never expose port 8080 publicly. Production Airflow requires a production auth manager, TLS, a secret backend and remote log/artifact storage.
- The optional PostgreSQL Compose service binds to `127.0.0.1` only. Replace its local-development password in `.env`, and never reuse that credential in a shared or cloud environment.
- Generated Statcast partitions, DuckDB databases, model artifacts, exports, logs, dashboard bundles, virtual environments, and dependency folders are excluded by `.gitignore` and can be recreated from the documented pipeline.
- The reviewed dashboard snapshot at `dashboard/src/data.json` contains public baseball data used to reproduce the authored dashboard; it contains no application credentials.

If a secret is committed accidentally, revoke or rotate it first, then remove it from the complete Git history before publishing again.
