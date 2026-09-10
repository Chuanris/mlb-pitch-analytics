# PostgreSQL operational store / PostgreSQL 操作型資料庫

The main DuckDB database remains the analytical OLAP store. This optional PostgreSQL service holds small, frequently updated operational records: ingestion runs, source-partition receipts, forecast requests/results, and user watchlists. Keeping these workloads separate demonstrates why OLTP and analytical storage have different schemas and access patterns.

主要 DuckDB 資料庫仍負責分析型 OLAP 工作。這個選用的 PostgreSQL 服務保存少量、經常更新的操作資料：擷取執行紀錄、來源分區收據、預測請求／結果與使用者觀察名單。兩者分離可清楚展示 OLTP 與分析儲存需要不同 schema 與存取模式。

## What this milestone proves / 此里程碑證明的能力

- Normalized tables with primary keys, foreign keys, unique keys, checks and cascade behavior
- Idempotent `INSERT ... ON CONFLICT` request creation under concurrent writers
- Atomic status/result updates with rollback on a failed constraint
- Composite, covering and partial indexes for operational access patterns
- Immutable numbered migrations guarded by SHA-256 checksums
- A real PostgreSQL integration suite in GitHub Actions

- 具備主鍵、外鍵、唯一鍵、檢查條件與 cascade 行為的正規化資料表
- 多個並行 writer 下仍只建立一筆資料的冪等 `INSERT ... ON CONFLICT`
- 約束失敗時可 rollback 的原子狀態／結果更新
- 對應操作查詢模式的複合、covering 與 partial indexes
- 以 SHA-256 保護、不可任意修改的編號 migration
- 在 GitHub Actions 使用真實 PostgreSQL 執行 integration tests

## Local setup / 本機設定

Requirements: Docker Desktop with Compose and Python 3.11+.

需求：Docker Desktop（含 Compose）與 Python 3.11+。

```powershell
Copy-Item .env.example .env
# Edit .env and use the same local password in both values.
# 編輯 .env，並在兩個設定值中使用相同的本機密碼。

docker compose up -d postgres
docker compose ps

.\.venv\Scripts\python.exe -m pip install -r requirements-oltp.txt

$env:MLB_OLTP_DATABASE_URL = 'postgresql://mlb_app:<local-password>@127.0.0.1:5432/mlb_operational'
.\.venv\Scripts\python.exe -m src.oltp_store migrate
.\.venv\Scripts\python.exe -m src.oltp_store demo
.\.venv\Scripts\python.exe -m src.oltp_store status
```

The demo performs the same forecast request twice with one idempotency key and verifies that both calls return one request ID. It never writes to DuckDB or the dashboard snapshot.

Demo 會以相同 idempotency key 建立兩次預測請求，並確認兩次都回傳同一個 request ID；它不會寫入 DuckDB 或儀表板快照。

## Integration tests / 整合測試

```powershell
$env:TEST_DATABASE_URL = $env:MLB_OLTP_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest tests.integration.test_postgres_oltp -v
```

The ordinary test suite skips PostgreSQL integration tests when `TEST_DATABASE_URL` or psycopg is unavailable. The `Data platform CI` workflow supplies both and therefore treats any skipped integration test as a setup defect to investigate in its logs.

一般測試在缺少 `TEST_DATABASE_URL` 或 psycopg 時會跳過 PostgreSQL integration tests；`Data platform CI` workflow 會提供兩者，因此若該 job 出現跳過測試，應視為需要查看 log 的設定問題。

## Security boundary / 安全界線

Compose binds PostgreSQL only to `127.0.0.1`. Its default credential is explicitly for local development; replace it in `.env`, which is Git-ignored. Do not reuse it in any cloud environment. A later cloud milestone will use workload identity/OIDC and least-privilege service accounts rather than committed credentials.

Compose 只把 PostgreSQL 綁定到 `127.0.0.1`。預設帳密明確只供本機開發使用；請在 Git 已排除的 `.env` 中更換，且不得用於雲端環境。後續雲端里程碑將使用 workload identity／OIDC 與最小權限服務帳號，不提交長期憑證。

## Resetting local data / 重設本機資料

`docker compose down` stops the service and preserves the named volume. Removing the volume deletes the local PostgreSQL data and is intentionally not part of the normal workflow.

`docker compose down` 只停止服務並保留 named volume。移除 volume 會刪除本機 PostgreSQL 資料，因此刻意不放進一般操作流程。

