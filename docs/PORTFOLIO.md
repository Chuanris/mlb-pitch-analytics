# Portfolio evidence and resume bullets / 作品集證據與履歷重點

Use this page to explain the engineering choices with evidence from the repository. Credential-free PostgreSQL, dbt, BigQuery, Terraform and Airflow contracts have run successfully in GitHub Actions; do not claim a live GCP deployment until the guarded cloud workflow completes in a personal cloud project.

這一頁用 repo 內可檢查的證據說明工程選擇。PostgreSQL、dbt、BigQuery、Terraform 與 Airflow 的免憑證 contracts 已在 GitHub Actions 成功執行；在 guarded cloud workflow 尚未於個人雲端專案完成前，不要宣稱已正式部署至 GCP。

## Job-description coverage / 職缺條件涵蓋度

| Capability | Repository evidence | Status |
| --- | --- | --- |
| SQL and performance | Window functions, conditional aggregation, incremental dbt model, date partitioning, clustering, configurable parallel threads, and a bytes/slot benchmark | Local SQL verified; live BigQuery metrics pending one cloud run |
| Traditional OLTP | PostgreSQL run/request/watchlist schema, constraints, idempotent writes, transactions, operational indexes and service-backed CI tests | Implemented; local Docker verification depends on Docker availability |
| MPP platform | BigQuery dbt target, merge strategy, `game_date` partition, `pitcher_id, pitch_type` clustering, IaC datasets and an executable verification query | Deployable and contract-tested; live run pending credentials/billing |
| Cloud storage and security | Private versioned GCS, enforced public-access prevention, repository/branch-scoped GitHub OIDC, split deploy/runtime identities and dataset/bucket-scoped runtime grants | Implemented as Terraform; live apply pending |
| Transformation tools | dbt source-to-staging-to-incremental-to-mart DAG, seed, documentation and 20 data tests | Implemented and verified on DuckDB |
| Medallion architecture | Bronze raw source, Silver staging/outcomes and Gold analytical marts | Implemented |
| DevOps | Airflow 3 daily DAG, bounded parallelism, retries/timeouts, PostgreSQL metadata, Git, GitHub Actions, Python/PostgreSQL/dbt tests, Terraform CI and protected cloud plan/apply | Six-job CI matrix verified; live scheduler service pending Docker |
| Communication | Matched English and Traditional Chinese README, operations, OLTP, dbt, cloud, Airflow, portfolio and AI-workflow guides | Implemented |
| AI proficiency | [AI workflow](AI_WORKFLOW.md), human-review boundaries, public failure-to-fix case study, PR evidence template and CI-enforced claim contracts | Implemented with traceable evidence; no unmeasured productivity claim |

## Verified evidence / 已驗證證據

As of the latest local and GitHub Actions verification:

- [Data platform CI run 34540760348](https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/34540760348) passed all six jobs: Python/pipeline contracts, PostgreSQL integration, two dbt builds, BigQuery parse/MPP contracts, two Terraform module validations and Airflow DAG execution.
- The [AI-assisted engineering case study](AI_WORKFLOW.md) traces an invalid workflow, environment-specific Python/Airflow failures, focused repair commits and the final six-job green run. The PR template requires human review, rejected-suggestion notes, validation evidence and claim/security checks.
- `dbt build` completed 25/25 resources: four models, one seed and 20 tests.
- A second fixture build retained exactly nine pitch rows, proving the incremental rerun did not duplicate the latest partition.
- Full-data dbt output matched the existing gold tables: 1,355,356 pitch rows, 13,288 pitcher/pitch-type mart rows and 56,191 count-strategy mart rows.
- The BigQuery target parsed with `dbt-bigquery==1.12.0`; its manifest records merge incrementality, daily partitioning and two clustering keys. Authentication and warehouse execution are still pending.
- Both Terraform modules are included in credential-free CI format/validate contracts. The guarded cloud workflow, OIDC boundary, landing manifest and BigQuery evidence collector are implemented, but no live GCP metrics should be claimed until an `apply` artifact exists.
- The Airflow DAG defines 15 tasks, two parallel stages, a serial DuckDB/dbt barrier, one active run, four active tasks, retries and execution/DAG timeouts. CI successfully imported, serialized and executed it in plan-only `dag.test()` mode; a live scheduler run should not be claimed until Docker or a managed Airflow environment completes it.

最近一次本機與 GitHub Actions 驗證結果：

- [Data platform CI run 34540760348](https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/34540760348) 的六個 jobs 全部成功：Python／pipeline contracts、PostgreSQL integration、兩次 dbt build、BigQuery parse／MPP contracts、兩個 Terraform modules validation，以及 Airflow DAG execution。
- [AI 輔助工程 case study](AI_WORKFLOW.md) 追蹤 invalid workflow、Python／Airflow 環境差異 failures、針對性修正 commits 與最終六個 jobs 全綠的 run；PR template 要求人工審核、被拒絕建議、驗證證據，以及 claims／security checks。
- `dbt build` 完成 25/25：四個 models、一個 seed、20 個 tests。
- Fixture 第二次執行後仍維持九筆逐球資料，證明 incremental rerun 沒有重複最新分區。
- 完整資料的 dbt 輸出與既有 gold 表一致：1,355,356 筆逐球、13,288 筆投手／球種 mart、56,191 筆球數策略 mart。
- BigQuery target 已以 `dbt-bigquery==1.12.0` 成功 parse；manifest 記錄 merge incremental、每日分區與兩個 clustering keys。雲端認證與 warehouse 實跑仍待完成。
- 兩個 Terraform modules 都已加入不需憑證的 CI format／validate contracts；具 guard 的 cloud workflow、OIDC 邊界、landing manifest 與 BigQuery evidence collector 已完成，但在 `apply` artifact 出現前不可宣稱真實 GCP metrics。
- Airflow DAG 定義 15 個 tasks、兩個平行階段、serial DuckDB／dbt barrier、單一 active run、四個 active tasks、retries 與 execution／DAG timeouts。CI 已成功匯入、序列化並以 plan-only `dag.test()` mode 執行；在 Docker 或 managed Airflow environment 真實完成前，不可宣稱 live scheduler run。

## Resume bullets ready to use / 可直接使用的履歷 bullet points

English:

- Built a tested medallion analytics pipeline for 1.35M+ MLB Statcast pitches using Python, DuckDB, SQL and dbt, producing reusable pitcher and count-strategy marts.
- Implemented an idempotent incremental dbt model and 20 schema/business/reconciliation tests; matched 1,355,356 pitch rows and both analytical marts against legacy gold outputs.
- Engineered a deployable GCS/BigQuery MPP platform with Terraform, merge-based dbt incrementality, daily partitioning, clustering and parallel execution while retaining a zero-cost DuckDB development target.
- Secured cloud CI/CD with repository- and branch-scoped GitHub OIDC, separate infrastructure/runtime identities, private versioned object storage, least-privilege dataset grants, manual approval and query-cost guards.
- Orchestrated a 15-task Airflow 3 daily pipeline with safe parallel extraction/product branches, serialized DuckDB/dbt write barriers, retry and timeout policies, overlap prevention and final health gates; validated DAG serialization and complete plan-only execution in GitHub Actions.
- Engineered a PostgreSQL OLTP companion for mutable pipeline and forecast state with relational constraints, transactional writes, idempotency keys and workload-specific indexes; automated service-backed integration tests in GitHub Actions.
- Documented architecture, metric denominators, security boundaries and operating procedures in English and Traditional Chinese, separating verified local results from pending cloud claims.
- Applied AI-assisted software engineering to analyze the repository, implement four data-platform capability stages and diagnose Linux CI failures; converted suggestions into human-reviewed commits and a six-job green evidence chain without inventing productivity metrics or live-cloud results.

繁體中文：

- 使用 Python、DuckDB、SQL 與 dbt 建立具測試的 Medallion 分析管線，處理超過 135 萬筆 MLB Statcast 逐球資料，產出可重用的投手與球數策略 marts。
- 實作可冪等重跑的 incremental dbt model 與 20 項 schema、商業規則及 reconciliation tests；1,355,356 筆逐球資料與兩個分析 marts 均對齊既有 gold 輸出。
- 使用 Terraform 建立可部署的 GCS／BigQuery MPP 平台，結合 dbt merge incremental、每日分區、clustering 與平行執行，同時保留零成本 DuckDB 開發 target。
- 以限定 repository／branch 的 GitHub OIDC、分離的 infrastructure／runtime identities、私有版本化 object storage、最小權限 dataset grants、人工核准與 query-cost guards 強化雲端 CI/CD。
- 使用 Airflow 3 編排 15-task daily pipeline，包含安全平行的 extraction／product branches、序列化 DuckDB／dbt write barriers、retry／timeout policies、防止重疊執行與最終 health gates，並在 GitHub Actions 驗證 DAG serialization 與完整 plan-only execution。
- 為可變動的 pipeline 與預測狀態建立 PostgreSQL OLTP 配套，涵蓋關聯約束、交易式寫入、冪等鍵與依工作負載設計的索引，並在 GitHub Actions 自動執行 service-backed integration tests。
- 以英文與繁體中文說明架構、指標分母、安全邊界與維運流程，清楚區分已驗證的本機結果與尚待執行的雲端項目。
- 使用 AI 輔助工程方法分析 repo、實作四個 data-platform capability stages 並診斷 Linux CI failures；將建議轉成經人工審核的 commits 與六個 jobs 全綠的證據鏈，不捏造 productivity metrics 或 live-cloud results。

## Interview story / 面試敘事

1. Start with the separation of workloads: PostgreSQL owns mutable operational state; DuckDB/BigQuery owns analytical scans.
2. Walk through the dbt lineage from raw source to deduplicated staging, incremental pitch outcomes and two marts.
3. Explain denominator correctness: whiffs divide by swings, chase events by out-of-zone pitches, and hard hits by measured batted balls.
4. Show the migration safety net: deterministic edge-case fixture plus full-data reconciliation against existing gold outputs.
5. Explain the cloud trust boundary and MPP proof: Terraform separates bootstrap/platform state, OIDC replaces stored keys, dbt runs under a narrower identity, and the final artifact measures bytes and slot time. Be explicit that live numbers require a successful cloud run.
6. Show orchestration judgment rather than only the graph: parallelize disjoint I/O and read-only products, serialize the shared DuckDB writer, cap concurrency, fail before extraction when the frozen model release is invalid, and finish with a health gate.

1. 先說明工作負載分離：PostgreSQL 負責會變動的操作狀態；DuckDB／BigQuery 負責分析掃描。
2. 依序展示 dbt lineage：raw source、去重 staging、incremental 逐球結果，以及兩個 marts。
3. 解釋分母正確性：揮空除以揮棒、追打除以好球帶外投球、強擊球除以有測得初速的擊球。
4. 展示遷移安全網：含邊界案例的 deterministic fixture，加上完整資料對既有 gold 的 reconciliation。
5. 說明 cloud trust boundary 與 MPP 證據：Terraform 拆分 bootstrap／platform state、OIDC 取代已儲存金鑰、dbt 使用較小權限 identity，最終 artifact 量測 bytes 與 slot time；同時明確指出真實數值必須來自成功的雲端執行。
6. 不只展示 DAG 圖，也解釋 orchestration 判斷：不重疊的 I/O 與 read-only products 才平行化；共享 DuckDB writer 保持序列；限制 concurrency；frozen model release 無效時在 extraction 前失敗；最後以 health gate 收尾。

### Conditional bullet after a successful cloud run / 雲端成功執行後才可使用

Replace the bracketed values only from `bigquery_verification.json`:

- Deployed and verified a BigQuery medallion pipeline through keyless GitHub OIDC; validated 9 deduplicated pitch facts and measured a partition-filtered query at `[bytes processed]` bytes and `[slot_millis]` slot-ms under a 100 MB billing guard.

只能用 `bigquery_verification.json` 的真實數字替換括號：

- 透過無長效金鑰的 GitHub OIDC 部署並驗證 BigQuery Medallion pipeline；確認 9 筆去重逐球 facts，並在 100 MB billing guard 下量測分區篩選查詢的 `[bytes processed]` bytes 與 `[slot_millis]` slot-ms。
