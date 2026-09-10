# Maintenance and publication / 維護與發布

[Dashboard](https://chuanris.github.io/mlb-pitch-analytics/) · [README](../README.md) · [Pages workflow](../.github/workflows/deploy-pages.yml)

## English

### Choose the workflow

| Task | Action from the repository root | Data impact |
| --- | --- | --- |
| Fix or preview UI | Build `dashboard/` with `npm.cmd ci` and `npm.cmd run build` | Keeps the committed snapshot |
| Preview pipeline steps | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow daily --dry-run` | No downloads or writes |
| Refresh current data | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow daily` | Requires a verified model release; updates recent scores and snapshot |
| Create a model release | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow retrain` | Retrains models and regenerates benchmark artifacts |
| Learn with a small dataset | `.\.venv\Scripts\python.exe run_pipeline.py --mode sample` | Replaces the snapshot with sample data; full-mode forecasts are omitted |
| Inspect local health | `.\.venv\Scripts\python.exe -m src.health_check --max-age-days 2` | Read-only; checks data age, lineage and pipeline status |
| Exercise PostgreSQL OLTP | `docker compose up -d postgres`, then `.\.venv\Scripts\python.exe -m src.oltp_store demo` | Writes local operational demo rows only; does not alter DuckDB or the dashboard |
| Validate dbt transformations | In `warehouse/`, run `..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb` | Writes only isolated `dbt_mlb_*` schemas and reconciles marts to legacy gold |
| Review GCP changes | Manually dispatch **GCP BigQuery portfolio deployment** with `operation=plan` | Read-only cloud plan; requires configured OIDC environment variables |
| Deploy GCP development fixture | Manually dispatch the same workflow with `operation=apply` and confirmation `DEPLOY` | Provisions GCS/BigQuery, replaces only isolated fixture sources, runs dbt twice, and records evidence |
| Validate Airflow topology | CI runs the real DAG with `MLB_AIRFLOW_EXECUTION_MODE=plan`; locally run `python orchestration/scripts/assert_dag_contract.py` in an Airflow 3.3.1 environment | Imports 15 tasks and checks dependencies/concurrency/timeouts without launching pipeline modules |
| Run local Airflow | `docker compose --env-file .env -f orchestration/compose.yaml up -d` after build/init | Starts localhost development services; DAG remains paused until reviewed and enabled |

The Windows daily task updates local files and rebuilds local HTML. It does **not** commit, push or deploy GitHub Pages. Publishing the latest data requires committing the reviewed `dashboard/src/data.json` snapshot and pushing it to `main`.

### Publish a reviewed change

1. Inspect `git status --short` and `git diff`. Keep local lessons, `.env`, raw data, databases, model files, outputs, logs and browser profiles out of the commit. Commit authored source, tests and the reviewed public snapshot together.
2. Run Python tests from the root: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`. Run `node --test dashboard/tests/mlb-pitch-analysis.test.mjs dashboard/tests/mlb-hitter-analysis.test.mjs` for the MLB aggregation and hitter decision helpers.
   When PostgreSQL is available, also set `TEST_DATABASE_URL` and run `.\.venv\Scripts\python.exe -m unittest tests.integration.test_postgres_oltp -v`; GitHub's `Data platform CI` workflow performs this against a real PostgreSQL service automatically.
   For transformation changes, install `requirements-dbt.txt`, then run `dbt build` twice from `warehouse/`; the second pass validates incremental idempotency. GitHub Actions repeats this with a deterministic DuckDB fixture.
   For infrastructure changes, inspect Terraform CI first, run the manual cloud workflow with `plan`, and only then approve `apply`. See [the cloud evidence guide](CLOUD.md); never point the fixture workflow at shared or production datasets.
   For orchestration changes, keep the canonical command builder in `run_pipeline.py`, run the Python suite, and pass the 15-task Airflow topology contract. A plan-only DAG test is not evidence of a completed refresh.
3. In `dashboard/`, run `npm.cmd ci` and `npm.cmd run build`. From the root, run `node scripts/check_compare.mjs prepublish`. Chrome must be installed; `CHROME_PATH` overrides its location.
4. Commit the reviewed files and push to `main`. Dashboard changes or changes to the browser-check script trigger the Pages workflow; documentation-only changes do not require rebuilding the site. The workflow can also be dispatched manually.
5. Check the matching commit in GitHub Actions. The workflow verifies the protected runtime, builds the HTML, runs analysis tests and checks Compare in Chrome before uploading the Pages artifact. Its `compare-browser-check` artifact retains JSON and desktop/mobile screenshots for seven days.
6. Open the deployed URL and check Compare and Hitters. The browser check also covers open dates, category switches, personal availability and replacement comparisons. To rerun it against the live site in PowerShell:

```powershell
$env:DASHBOARD_URL = 'https://chuanris.github.io/mlb-pitch-analytics/'
try { node scripts/check_compare.mjs published-check }
finally { Remove-Item Env:DASHBOARD_URL }
```

The check writes evidence under `outputs/performance/` and exits nonzero on a browser exception, missing selectors/navigation or page overflow. It measures the specified site; the pipeline health command does not verify deployment. Keep a local build available when running this helper.

### Troubleshooting

| Symptom | Check and recovery |
| --- | --- |
| Compare blanks the page | An empty canvas must not be mounted. Keep the `activeRows.length > 0` guard around `SortableRegion`; rebuild and deploy the new HTML. |
| Public page still looks old | Check the deployed commit in Actions, then hard-refresh the page. A local build alone cannot update Pages. |
| Compare has no forecasts | Inspect the snapshot mode and data cutoff. Sample mode intentionally omits full-mode forecasts; a missing probable start remains unknown. |
| Daily update refuses a release | Inspect the reported missing/modified artifact or configuration change. Restore matching inputs or explicitly retrain; do not delete lineage checks. |
| Health status needs attention | Read `outputs/pipeline_status.json`, `logs/` and the health command's detail. Account for off-season and UTC calendar dates. |
| dbt cannot open DuckDB | Stop local processes that hold the database file, or set `DBT_DUCKDB_PATH` to an isolated fixture/copy; never delete the production database to clear a lock. |
| Cloud workflow cannot authenticate | Confirm all eight `gcp-dev` environment variables, the repository/branch condition, and `id-token: write`; new IAM federation may need several minutes to propagate. Do not replace OIDC with a committed JSON key. |
| Airflow DAG is missing or has import errors | Confirm Airflow 3.3.1/Python 3.12, `MLB_PROJECT_ROOT`, the mounted `orchestration/dags` path and DAG processor health. Do not downgrade the DAG to deprecated Airflow 2 import paths. |
| Daily DAG fails at model release verification | Run the explicit retraining workflow and inspect lineage evidence. The preflight intentionally blocks extraction and downstream writes when the frozen release is missing or changed. |
| Pages fails before upload | Ensure repository Settings → Pages uses GitHub Actions; inspect the failed build/check before rerunning. |

The site is a self-contained static snapshot. A public deployment is not an automatically refreshed backend, and browser-local player labels stay on that browser.

## 繁體中文

### 選擇正確流程

| 工作 | 從專案根目錄執行的操作 | 對資料的影響 |
| --- | --- | --- |
| 修正或預覽介面 | 在 `dashboard/` 執行 `npm.cmd ci` 與 `npm.cmd run build` | 保留儲存庫內的快照 |
| 預覽資料流程 | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow daily --dry-run` | 不下載、不寫入 |
| 更新近期資料 | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow daily` | 需要已驗證模型版本；更新近期評分與快照 |
| 建立模型版本 | `.\.venv\Scripts\python.exe run_pipeline.py --mode full --workflow retrain` | 重訓模型並重新產生固定基準產物 |
| 使用小型教學資料 | `.\.venv\Scripts\python.exe run_pipeline.py --mode sample` | 替換為 Sample 快照，不包含完整模式預測 |
| 檢查本機健康狀態 | `.\.venv\Scripts\python.exe -m src.health_check --max-age-days 2` | 唯讀檢查資料日期、血緣與流程狀態 |
| 驗證 PostgreSQL OLTP | `docker compose up -d postgres`，再執行 `.\.venv\Scripts\python.exe -m src.oltp_store demo` | 只寫入本機操作型 demo 資料，不修改 DuckDB 或儀表板 |
| 驗證 dbt 轉換 | 在 `warehouse/` 執行 `..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb` | 只寫入隔離的 `dbt_mlb_*` schemas，並將 marts 對照既有 gold |
| 檢查 GCP 變更 | 手動執行 **GCP BigQuery portfolio deployment** 並設定 `operation=plan` | 唯讀雲端 plan；需先設定 OIDC environment variables |
| 部署 GCP 開發 fixture | 手動執行相同 workflow，設定 `operation=apply` 並輸入 `DEPLOY` | 建立 GCS／BigQuery，只替換隔離的 fixture sources，執行兩次 dbt 並保存證據 |
| 驗證 Airflow topology | CI 以 `MLB_AIRFLOW_EXECUTION_MODE=plan` 執行真實 DAG；本機可在 Airflow 3.3.1 環境執行 `python orchestration/scripts/assert_dag_contract.py` | 匯入 15 個 tasks 並檢查 dependencies／concurrency／timeouts，不啟動 pipeline modules |
| 執行本機 Airflow | 完成 build／init 後執行 `docker compose --env-file .env -f orchestration/compose.yaml up -d` | 啟動 localhost 開發服務；DAG 在人工檢查與啟用前保持暫停 |

Windows 每日排程只更新本機檔案並重建本機 HTML，**不會**自動 commit、push 或部署 GitHub Pages。發布新資料時，須檢查並提交 `dashboard/src/data.json`，再推送至 `main`。

### 發布已檢查的變更

1. 檢查 `git status --short` 與 `git diff`。個人 lesson、`.env`、原始資料、資料庫、模型、outputs、日誌與瀏覽器設定檔保持在本機；功能原始碼、測試與已檢查的公開快照一併提交。
2. 在根目錄執行 Python 測試：`.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`；執行 `node --test dashboard/tests/mlb-pitch-analysis.test.mjs dashboard/tests/mlb-hitter-analysis.test.mjs` 驗證 MLB 聚合與打者決策邏輯。
   若 PostgreSQL 可用，也要設定 `TEST_DATABASE_URL`，並執行 `.\.venv\Scripts\python.exe -m unittest tests.integration.test_postgres_oltp -v`；GitHub 的 `Data platform CI` workflow 會自動以真實 PostgreSQL service 執行這項測試。
   修改轉換邏輯時，請安裝 `requirements-dbt.txt`，並在 `warehouse/` 連續執行兩次 `dbt build`；第二次驗證 incremental 冪等性。GitHub Actions 會用 deterministic DuckDB fixture 重複同一流程。
   修改基礎設施時，先確認 Terraform CI，再手動執行雲端 `plan`，最後才核准 `apply`。詳見[雲端證據指南](CLOUD.md)；fixture workflow 不可指向共享或 production datasets。
   修改 orchestration 時，canonical command builder 必須保留在 `run_pipeline.py`，並通過 Python suite 與 15-task Airflow topology contract。Plan-only DAG test 不等於實際資料 refresh。
3. 在 `dashboard/` 執行 `npm.cmd ci` 與 `npm.cmd run build`，回根目錄執行 `node scripts/check_compare.mjs prepublish`。需安裝 Chrome；可透過 `CHROME_PATH` 指定安裝位置。
4. 提交檢查過的檔案並推送至 `main`。儀表板或瀏覽器檢查腳本有變更時，Pages workflow 自動啟動；純文件變更不必重建網站，也可手動啟動 workflow。
5. 在 GitHub Actions 確認對應 commit。流程先驗證受保護執行環境、建置 HTML、測試聚合邏輯並用 Chrome 點擊 Compare，通過後才上傳 Pages 產物。`compare-browser-check` artifact 保存 JSON 與桌面／手機截圖七天。
6. 開啟正式網址並檢查 Compare 與 Hitters。瀏覽器檢查也包含空缺日、類別切換、個人可用名單與替換比較。若要在 PowerShell 自動檢查正式網站：

```powershell
$env:DASHBOARD_URL = 'https://chuanris.github.io/mlb-pitch-analytics/'
try { node scripts/check_compare.mjs published-check }
finally { Remove-Item Env:DASHBOARD_URL }
```

檢查證據寫入 `outputs/performance/`；瀏覽器例外、缺少選單／導覽或頁面溢出時回傳非零結束碼。此指令檢查指定網站，資料健康指令不驗證部署。執行此工具時仍須保留本機建置。

### 故障排除

| 現象 | 檢查與處理 |
| --- | --- |
| 點 Compare 後整頁空白 | 不應建立空的 canvas；保留 `SortableRegion` 外的 `activeRows.length > 0` 防護，重新建置並發布 HTML。 |
| 公開頁面仍是舊版 | 確認 Actions 部署的 commit，再強制重新整理；只建置本機檔案不會更新 Pages。 |
| Compare 沒有預測 | 檢查快照模式與資料日期。Sample 刻意不包含完整模式預測；未確認的預定先發保留未知。 |
| 每日更新拒絕模型版本 | 查看缺失／修改的產物或設定變動，恢復相符輸入或明確重訓，不要移除血緣檢查。 |
| 健康檢查要求留意 | 讀取 `outputs/pipeline_status.json`、`logs/` 與檢查細節，考慮休賽期與 UTC 日曆日。 |
| dbt 無法開啟 DuckDB | 停止占用資料庫檔案的本機程序，或將 `DBT_DUCKDB_PATH` 指向隔離的 fixture／副本；不要為了解除鎖定而刪除正式資料庫。 |
| Cloud workflow 無法驗證身份 | 確認八個 `gcp-dev` environment variables、repository／branch condition 與 `id-token: write`；新 IAM federation 可能需數分鐘生效。不要改用已提交的 JSON key。 |
| Airflow DAG 未出現或發生 import error | 確認 Airflow 3.3.1／Python 3.12、`MLB_PROJECT_ROOT`、掛載的 `orchestration/dags` path 與 DAG processor health；不要改回 deprecated Airflow 2 import paths。 |
| Daily DAG 在 model release verification 失敗 | 執行明確的 retraining workflow 並檢查 lineage evidence。Frozen release 缺失或改變時，preflight 會刻意在 extraction 與 downstream writes 前阻擋流程。 |
| Pages 在上傳前失敗 | 確認 Settings → Pages 使用 GitHub Actions，先查看失敗的建置／檢查再重新執行。 |

網站是自含資料的靜態快照，公開部署不代表後端會自動刷新；球員清單標記只保存在操作的瀏覽器。
