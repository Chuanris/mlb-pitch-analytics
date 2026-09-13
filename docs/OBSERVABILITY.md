# Data observability / 資料可觀測性

`src.validate_data` now records observations before enforcing its quality gate. Both the pipeline CLI and the existing Airflow `validate_data` task use this entry point. A freshness breach exits 1; an invalid dataset, schema change, volume anomaly or failed SQL check exits 2. Downstream tasks stop under their existing success dependencies. Each attempt records its own ID, timestamp, metrics, SQL check outcomes, alerts and suggested actions.

`src.validate_data` 會先保存觀測紀錄，再執行品質閘門。Pipeline CLI 與既有 Airflow `validate_data` task 共用此入口。新鮮度超標回傳 1；無效資料、schema 變更、筆數異常或 SQL 檢查失敗回傳 2。下游依既有成功依賴停止。每次嘗試都有自己的 ID、時間、指標、SQL 檢查結果、提醒及處理建議。

## Policy / 規則

The independent [policy file](../config/observability.json) keeps model lineage configuration unchanged:

| Check | Rule | Baseline |
| --- | --- | --- |
| Freshness | At most two calendar days behind the configured expected end date | Uses dataset mode; active full ranges are capped at yesterday UTC, historical/sample ranges at their configured end |
| Row volume | Total pitch rows between 0.90 and 1.50 times the prior successful total | Last passing observation in the same scope |
| Schema drift | Ordered column names and SQL types match | First passing observation in the same scope |
| Data quality | All existing SQL checks pass; SQL exceptions and null results fail | Existing `src.validate_data.CHECKS` |

獨立的 [policy file](../config/observability.json)設定兩天 freshness 容許值與 0.90–1.50 的總筆數比例。Freshness 依資料庫的 mode 判斷：歷史／sample 對照設定截止日；動態 full range 以 UTC 昨天為上限。Schema 比較欄位名稱、順序與 SQL 型別；既有 SQL 品質檢查也一併保存，查詢例外或 null 不算通過。

Scope includes the source path, mode, configured date ranges and policy. The first successful observation bootstraps schema and volume baselines and explicitly reports that no comparison was available. Failed or attention observations never replace a baseline. A rejected schema remains rejected on retries. A path/range/policy change starts a new scope; review such changes as baseline changes, especially during migrations. Preserve the old history for audit.

Scope 包含來源路徑、mode、日期設定與 policy。第一次成功觀測建立基準，並明確顯示尚無比較值。失敗或 attention 紀錄不更新基準，因此重試不會把錯誤 schema 接受成正常。改動路徑、日期或 policy 會建立新 scope，遷移時應將這些改動視為 baseline 變更審查，保留舊歷史供稽核。

## Run and inspect / 執行與查閱

```powershell
# Full quality gate plus history; read-only access to source DuckDB
.\.venv\Scripts\python.exe -m src.validate_data

# Same observation checks, JSON output, without coverage-export steps
.\.venv\Scripts\python.exe -m src.observability

# Fault-injection tests use temporary synthetic databases
.\.venv\Scripts\python.exe -m unittest tests.test_observability -v
```

The Git-ignored `outputs/observability/` directory contains:

- `history.sqlite`: transactional observation history, indexed by scope and status;
- `<run_id>.json`: a separate record for every attempt, including failures;
- `latest.json`: atomically replaced convenience snapshot.

SQL quality results also remain in `outputs/data_quality_report.csv`. SQLite is the authoritative history; JSON is a convenient export. SQLite baseline selection and insertion share a write transaction. The existing Airflow run-concurrency limit remains in force. A concurrent reader should use the SQLite sequence for ordering, since completion of JSON exports can race across separate processes.

Git 排除的 `outputs/observability/` 保存 SQLite 交易式歷史、每次嘗試獨立的 JSON，以及原子替換的 latest snapshot。SQLite 是歷史依據，JSON 供查閱；基準查詢與新增紀錄在同一個寫入交易內完成。多程序的 JSON 匯出可能交錯，歷史排序以 SQLite sequence 為準。

## Recovery and evidence / 恢復與證據

Read the named alert before rerunning. For freshness, inspect the configured ranges, extraction logs and game calendar. For row volume, investigate truncation, duplicate loading or an intentional backfill. For schema drift, review the migration and consumers before creating a new baseline scope. Fix the source and rerun; the old failures stay in history and the new passing observation records recovery.

重跑前先查看 alert：freshness 檢查日期設定、擷取紀錄與球賽日曆；筆數異常檢查截斷、重複載入或刻意 backfill；schema drift 先檢查 migration 與 downstream consumers。修復來源後重跑，舊失敗仍保留，新通過紀錄表達恢復。

[Fault tests](../tests/test_observability.py) cover historical sample freshness, successful bootstrap, an 80% volume loss, repeated rejection without baseline poisoning, recovery, persistent added-column drift, missing required columns, stale/empty data, SQL failure and invalid policy. CI replays these tests in its Python job. Airflow surfaces exit failures and the `ALERT` messages through its normal task logs and retries. No outbound email, Slack or paging integration is configured.

[故障測試](../tests/test_observability.py)涵蓋歷史 sample、新基準、80% 筆數流失、重試不污染基準、恢復、持續的新增欄位 drift、必要欄位遺失、過期／空資料、SQL 失敗與錯誤 policy。CI 在 Python job 重播；Airflow 透過 task logs、失敗狀態及 retries 顯示事件。目前沒有外部 email、Slack 或 paging 通知。

Freshness is a calendar proxy, not a schedule-aware completeness proof. Total-volume bounds detect large changes; they may miss a single missing day in a large historical table and do not model seasonal daily volume. Schema comparison currently covers `silver.fact_pitch`. Initial schema acceptance depends on existing SQL checks, so bootstrap is not proof of an approved schema contract. These are explicit boundaries of this implementation.

Freshness 是 calendar proxy，不能證明球賽完整性。總筆數比例可偵測大幅變動，但龐大歷史表漏一天仍可能未超標，也尚未建立季節性每日筆數模型。Schema 比較目前涵蓋 `silver.fact_pitch`；初次接受依賴既有 SQL 檢查，bootstrap 不等於 schema 已經人工核准。

## Resume bullet / 履歷重點

- Implemented persistent data observability for a DuckDB analytics pipeline with freshness gates, schema-drift detection, volume thresholds and SQL quality history; integrated failure propagation into Airflow and verified retry-safe baselines and recovery using injected faults.
- 為 DuckDB 分析管線實作持久化資料觀測，涵蓋 freshness 閘門、schema drift、筆數閾值與 SQL 品質歷史；串接 Airflow 失敗傳遞，並用故障注入驗證重試基準與恢復行為。
