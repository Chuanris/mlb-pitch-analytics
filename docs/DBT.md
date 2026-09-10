# dbt transformation layer / dbt 轉換層

This directory turns one representative analytics path into a tested dbt DAG that runs locally on DuckDB and is ready to deploy to BigQuery. It is deliberately isolated from the existing dashboard build: dbt writes only to schemas prefixed by `DBT_SCHEMA` and never edits `dashboard/src/data.json`.

這個目錄把一條具代表性的分析路徑改造成有測試的 dbt DAG，可在本機 DuckDB 執行，也可部署到 BigQuery。它刻意與既有儀表板建置隔離：dbt 只寫入以 `DBT_SCHEMA` 為前綴的 schema，不會修改 `dashboard/src/data.json`。

## Model DAG / 模型 DAG

```text
bronze.raw_statcast + metadata.pipeline_ranges
                    |
                    v
       dbt_mlb_silver.stg_statcast      (view: scoped and deduplicated)
                    |
                    v
       dbt_mlb_silver.int_pitch_outcomes (incremental: outcome flags)
                    |
             +------+------+
             v             v
 dbt_mlb_gold.mart_pitcher_pitch_type
 dbt_mlb_gold.mart_count_strategy
```

`pitch_type_mapping.csv` is a governed dbt seed. The marts preserve the production definitions of whiff, chase, hard-hit and zone rate. DuckDB-only reconciliation tests compare stable dimensions and counts against the existing `gold` tables during migration.

`pitch_type_mapping.csv` 是受版本控制的 dbt seed。兩個 mart 保留正式環境的揮空率、追打率、強擊球率與進壘率定義；遷移期間，DuckDB 專用 reconciliation tests 會把穩定維度與計數對照既有 `gold` 表。

## Local DuckDB workflow / 本機 DuckDB 流程

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dbt.txt
Set-Location warehouse
..\.venv\Scripts\dbt.exe debug --profiles-dir . --target duckdb
..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb
```

The default profile reads the existing `database/mlb_pitch_analytics.duckdb` and writes `dbt_mlb_reference`, `dbt_mlb_silver`, and `dbt_mlb_gold`. Override the database or schema prefix without editing committed configuration:

預設 profile 讀取現有 `database/mlb_pitch_analytics.duckdb`，並寫入 `dbt_mlb_reference`、`dbt_mlb_silver` 與 `dbt_mlb_gold`。若要更換資料庫或 schema 前綴，不需修改已提交的設定：

```powershell
$env:DBT_DUCKDB_PATH = 'C:\data\mlb.duckdb'
$env:DBT_SCHEMA = 'yourname_mlb'
$env:DBT_THREADS = '4'
try {
    Set-Location warehouse
    ..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb
} finally {
    Remove-Item Env:DBT_DUCKDB_PATH, Env:DBT_SCHEMA, Env:DBT_THREADS -ErrorAction SilentlyContinue
}
```

Run the build twice when validating incremental behavior. The second run reprocesses the latest date only and the `unique_key` prevents duplicate pitch rows.

驗證 incremental 行為時請連續執行兩次；第二次只重處理最新日期，`unique_key` 會防止重複的逐球資料。

## Deterministic CI smoke test / 可重現的 CI 快速測試

The fixture includes a late duplicate, excluded spring-training and out-of-range rows, an unmapped pitch type, a missing exit-velocity denominator, and manually specified legacy aggregates:

測試資料涵蓋較晚重複列、應排除的春訓與日期範圍外資料、未映射球種、缺少擊球初速的分母，以及人工指定的舊版彙總結果：

```powershell
$fixture = (Resolve-Path .).Path + '\warehouse\ci.duckdb'
.\.venv\Scripts\python.exe warehouse\scripts\create_ci_fixture.py $fixture
$env:DBT_DUCKDB_PATH = $fixture
try {
    Set-Location warehouse
    ..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb
    ..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb
} finally {
    Remove-Item Env:DBT_DUCKDB_PATH -ErrorAction SilentlyContinue
}
```

GitHub Actions runs this same fixture path and both dbt builds, so a pull request proves a clean full build and an idempotent incremental rerun. A separate credential-free job parses the BigQuery target and asserts the merge, partition and clustering contract in the generated manifest.

GitHub Actions 會執行相同 fixture 與兩次 dbt build，因此 pull request 可證明乾淨的完整建置與冪等 incremental rerun。另一個不需憑證的 job 會 parse BigQuery target，並檢查產生的 manifest 是否保留 merge、partition 與 clustering contract。

## BigQuery target / BigQuery 目標

Install the optional adapter and use Application Default Credentials; do not commit service-account keys:

安裝選用 adapter 並使用 Application Default Credentials；不要提交 service-account 金鑰：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dbt-bigquery.txt
gcloud auth application-default login

$env:DBT_TARGET = 'bigquery'
$env:DBT_BIGQUERY_PROJECT = 'your-gcp-project'
$env:DBT_SCHEMA = 'dbt_mlb_dev'
$env:DBT_BRONZE_SCHEMA = 'bronze'
$env:DBT_METADATA_SCHEMA = 'metadata'
$env:DBT_THREADS = '8'

Set-Location warehouse
..\.venv\Scripts\dbt.exe build --profiles-dir . --target bigquery
```

Before the first cloud run, load `bronze.raw_statcast` and `metadata.pipeline_ranges` into datasets in `DBT_BIGQUERY_PROJECT`, or set `DBT_SOURCE_DATABASE` to the source project. The incremental pitch model is partitioned by `game_date` and clustered by `pitcher_id, pitch_type`; independent downstream marts can execute in parallel up to `DBT_THREADS`. These controls demonstrate MPP-aware design, but they do not claim a live BigQuery deployment until credentials and billing are supplied and the run is verified.

第一次執行雲端流程前，請把 `bronze.raw_statcast` 與 `metadata.pipeline_ranges` 載入 `DBT_BIGQUERY_PROJECT` 的 datasets，或用 `DBT_SOURCE_DATABASE` 指定來源 project。逐球 incremental model 依 `game_date` 分區，並以 `pitcher_id, pitch_type` 叢集；彼此獨立的下游 marts 最多可依 `DBT_THREADS` 平行執行。這些設定展示 MPP 導向的設計，但在尚未提供憑證、計費並完成實際執行前，不應宣稱已部署 BigQuery。

## What the tests prove / 測試能證明什麼

- Natural pitch keys are unique and required dimensions are non-null.
- Outcome flags and count states stay within accepted domains.
- Rates remain in `[0, 1]` and numerators cannot exceed their denominators.
- Mart grains are unique.
- DuckDB migration counts match the existing production gold tables.
- A second incremental build does not duplicate the latest partition.

- 逐球自然鍵唯一，必要維度不可為空值。
- 結果旗標與球數狀態落在允許範圍。
- 比率維持在 `[0, 1]`，且分子不會超過分母。
- Mart grain 保持唯一。
- DuckDB 遷移後的計數與既有正式 gold 表一致。
- 第二次 incremental build 不會重複最新分區。
