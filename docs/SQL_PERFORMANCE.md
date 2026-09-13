# SQL performance and parallelism / SQL 效能與平行度

This repository includes a reproducible DuckDB benchmark over the local Silver layer. It turns the broad claim "understands SQL performance and parallelism" into inspectable query text, repeated wall-clock measurements, `EXPLAIN ANALYZE` plans and cross-thread correctness checks.

本 repo 提供一套可重跑的 DuckDB benchmark，直接在本機 Silver layer 上量測。它把「理解 SQL 效能與平行度」轉成可檢查的查詢文字、重複 wall-clock 測量、`EXPLAIN ANALYZE` 計畫，以及跨 thread 的結果正確性檢查。

## Verified snapshot / 已驗證快照

The committed [machine-readable result](../benchmarks/results/latest.json), [readable table](../benchmarks/results/latest.md) and [operator plans](../benchmarks/results/explain/) were generated on 2026-09-12 Pacific time from:

- DuckDB 1.5.5 on Windows 11 with 16 logical CPUs visible;
- a 1,665,675,264-byte local database;
- 1,355,356 rows in `silver.fact_pitch`, covering 2025-03-18 through 2026-09-09;
- 4,626 rows in `silver.fact_game_context`;
- five measured warm runs after one warm-up for each 1/2/4/8-thread configuration.

已提交的 [JSON 結果](../benchmarks/results/latest.json)、[可讀表格](../benchmarks/results/latest.md)與 [operator plans](../benchmarks/results/explain/)是在 Pacific time 2026-09-12 產生，資料與環境如下：

- Windows 11、DuckDB 1.5.5，可見 16 個 logical CPUs；
- 本機資料庫大小 1,665,675,264 bytes；
- `silver.fact_pitch` 有 1,355,356 rows，日期為 2025-03-18 至 2026-09-09；
- `silver.fact_game_context` 有 4,626 rows；
- 每個 1／2／4／8-thread 設定先 warm-up 一次，再量測五次 warm runs。

| Workload | 1 thread median | Best measured median | Observed speedup | What it demonstrates |
| --- | ---: | ---: | ---: | --- |
| Full scan + grouped aggregate | 56.151 ms | 29.094 ms at 8 threads | 1.930x | Parallel scan/aggregation helps, but scaling is not linear |
| 30-day filter + aggregate | 16.049 ms | 12.592 ms at 4 threads | 1.275x | The 120,746-row predicate (8.909% of facts) needs less work; 8 threads add no benefit here |
| Fact-to-dimension join + aggregate | 40.672 ms | 20.818 ms at 8 threads | 1.954x | The hash join and aggregate benefit from more parallel work |
| Grouped input + partitioned window | 155.185 ms | 133.200 ms at 8 threads | 1.165x | Window/sort/materialization work scales much less than the scan and join workloads |

These numbers are evidence for this machine and snapshot, not universal DuckDB claims. Every result row count and SHA-256 matched across all thread counts.

以上是這台機器與這份資料快照的證據，不代表所有 DuckDB workload。四類查詢在所有 thread 設定下的輸出 row count 與 SHA-256 都一致。

## Query suite / 查詢組合

The SQL stays separate from the runner so a reviewer can inspect each workload:

- [`01_full_scan_aggregate.sql`](../benchmarks/sql/01_full_scan_aggregate.sql): scans the pitch fact table and groups by pitcher and pitch type.
- [`02_recent_filter_aggregate.sql`](../benchmarks/sql/02_recent_filter_aggregate.sql): repeats the aggregate for the latest 30 inclusive dates.
- [`03_game_context_join.sql`](../benchmarks/sql/03_game_context_join.sql): joins 1.35M pitch facts to game context, then aggregates by venue, day/night and pitch type.
- [`04_partitioned_window.sql`](../benchmarks/sql/04_partitioned_window.sql): creates pitcher-date groups and calculates rolling ten-date counts with partitioned windows.

SQL 與 runner 分開保存，reviewer 可以直接檢查每一類 workload：full scan aggregation、recent-date predicate、fact-to-dimension hash join，以及 partitioned window。

The runner uses the supported DuckDB `SET threads TO n` setting and records `EXPLAIN ANALYZE` for each query. DuckDB documents that `EXPLAIN ANALYZE` executes the query and reports actual operator cardinalities and timing; it also notes that parallel operator time can add up to more than wall-clock time. See the official [configuration](https://duckdb.org/docs/current/configuration/overview) and [`EXPLAIN ANALYZE`](https://duckdb.org/docs/current/guides/meta/explain_analyze) documentation.

## Reproduce / 重跑方式

Run from the repository root with the project Python environment:

```powershell
.\.venv\Scripts\python.exe benchmarks\run_duckdb_benchmark.py `
  --threads 1,2,4,8 `
  --repetitions 5 `
  --warmups 1
```

For a fast runner check without plans:

```powershell
.\.venv\Scripts\python.exe benchmarks\run_duckdb_benchmark.py --quick
```

Quick mode writes ignored `quick.json` and `quick.md` files, so it cannot overwrite the committed full evidence accidentally.

The full command overwrites only these regenerable benchmark evidence files:

- `benchmarks/results/latest.json`
- `benchmarks/results/latest.md`
- `benchmarks/results/explain/*.txt`

The source database is opened with `read_only=True`. The runner does not extract data, rebuild tables or modify `database/mlb_pitch_analytics.duckdb`.

完整指令只會覆寫上述 benchmark 證據檔；來源 DuckDB 以 `read_only=True` 開啟，不會下載資料、重建資料表或修改資料庫。

## Measurement and correctness design / 測量與正確性設計

- `time.perf_counter_ns` measures wall-clock time around execution plus complete `fetchall()` materialization.
- `first_observed_ms` is stored separately. It is intentionally not called a cold-cache result because the runner cannot evict the operating-system file cache reliably.
- Median is the comparison statistic; p95, minimum, maximum and every raw run remain in JSON.
- The latest-data predicate is derived from `MAX(game_date)` rather than today's date, so an older snapshot remains reproducible.
- The date filter demonstrates predicate selectivity in this DuckDB file. It does not claim physical partition pruning; the BigQuery target has a separate partition contract.
- Each query must return the same ordered row count and SHA-256 for every thread setting or the run fails before writing evidence.
- Exact checksum validation initially exposed non-associative floating-point `AVG(DOUBLE)` differences between parallel reduction orders. The benchmark now casts velocity to fixed-point decimal before averaging, so the result invariant is exact instead of tolerance-based.

- `time.perf_counter_ns` 量測 SQL 執行加完整 `fetchall()` materialization 的 wall-clock time。
- `first_observed_ms` 獨立保存，但不稱為 cold-cache，因為 runner 無法可靠清除作業系統 file cache。
- 以 median 作為比較值；p95、最小值、最大值與每次原始測量都保留在 JSON。
- 最新日期 filter 由資料內的 `MAX(game_date)` 推導，因此舊 snapshot 仍可重跑。
- DuckDB 的日期條件只證明 predicate selectivity，不宣稱 physical partition pruning；BigQuery target 另有分區 contract。
- 任一 query 在不同 thread 下的 ordered row count 或 SHA-256 不同，runner 就會失敗且不寫出證據。
- 初版 checksum gate 抓到 `AVG(DOUBLE)` 因平行歸約順序造成的非結合性浮點差異；目前在平均前先轉 fixed-point decimal，因此可做精確而非 tolerance-based 的結果驗證。

## What to say in an interview / 面試說法

1. Start with the hypothesis: scans and joins should have more parallel work than a selective query or an ordered window.
2. Explain the experiment: hold the database/query/result constant, vary only DuckDB threads, warm once, repeat five times and compare medians.
3. Show correctness before speed: row counts and checksums must match across thread counts.
4. Read the result honestly: 8 threads nearly halved the full-scan and join medians, while the recent filter peaked at 4 and the window improved only modestly.
5. State the boundary: this local DuckDB experiment demonstrates parallel query reasoning; BigQuery MPP evidence remains a separate cloud workflow and should not be inferred from laptop latency.

1. 先提出假設：scan 與 join 可平行的工作較多；選擇性高的 filter 或需要排序的 window 未必同樣受益。
2. 說明實驗控制：固定 database、SQL 與輸出，只改 DuckDB thread 數；warm-up 一次、量測五次並比較 median。
3. 先證明正確再談速度：不同 thread 下的 row count 與 checksum 必須一致。
4. 如實解讀：8 threads 讓 full scan 與 join median 接近減半；recent filter 在 4 threads 最佳；window 只小幅改善。
5. 說清楚界線：這是本機 DuckDB 的平行查詢實驗；BigQuery MPP 證據屬於另一個雲端 workflow，不能由 laptop latency 推論。

## Resume bullet / 履歷 bullet

- Built a reproducible DuckDB SQL benchmark over 1.36M pitch facts with full scans, selective filters, hash joins and partitioned windows; verified exact results across 1/2/4/8 threads and measured up to 1.95x median speedup on scan/join workloads while documenting non-linear scaling and cache limits.
- 建立可重跑的 DuckDB SQL benchmark，涵蓋 136 萬筆逐球 facts 的 full scan、selective filter、hash join 與 partitioned window；驗證 1／2／4／8 threads 的結果完全一致，scan／join workload 的 median latency 最多改善 1.95x，並記錄非線性 scaling 與 cache 限制。
