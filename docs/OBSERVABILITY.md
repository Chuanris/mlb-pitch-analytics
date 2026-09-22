# Data observability / 資料可觀測性

`src.validate_data` persists observations before enforcing the pipeline gate; `src.observability` runs the same checks without coverage exports. Overall precedence is error (exit 2), attention (exit 1), otherwise pass (exit 0). Both nonzero exits stop downstream tasks under existing pipeline/Airflow success dependencies.

`src.validate_data` 先保存觀測，再執行管線閘門；`src.observability` 執行相同檢查但不匯出 coverage。整體狀態優先順序為 error（exit 2）、attention（exit 1）、其餘 pass（exit 0）。兩種非零退出碼都會依既有 pipeline／Airflow 成功依賴停止下游。

## Policy / 規則

The [policy](../config/observability.json) is independent of model lineage configuration.

[Policy](../config/observability.json) 與模型 lineage 設定分開。

| Check / 檢查 | Current contract / 目前契約 |
| --- | --- |
| Freshness | More than 2 days behind the configured expected end: attention. Empty data or rows after the configured complete-date cutoff: error. Active ranges use yesterday in America/Los_Angeles without relying on the machine timezone. / 落後截止日超過 2 天為 attention；空資料或超過完整日期 cutoff 的資料為 error。動態 range 使用 America/Los_Angeles 的昨天，不依賴機器時區。 |
| Global row volume | Total pitch rows outside 0.90–1.50 times the previous successful total: error. This cross-run gate is unchanged. / 總筆數超出前次成功 run 的 0.90–1.50 倍仍為 error；跨 run 閘門未改動。 |
| Schema drift | Ordered names/types in silver.fact_pitch differ from the first passing run in scope: error. / 與同 scope 首次成功 run 的欄位名稱、順序或型別不同為 error。 |
| Data quality | Failed SQL checks, SQL exceptions and NULL results fail the gate. / SQL 檢查失敗、查詢例外或 NULL 均使閘門失敗。 |

## Recent-partition contract / 最近分區契約

The output key remains `recent_partition_completeness`. A pass means only that the evaluated date meets local coverage/status rules and configured volume heuristics; it does not prove source completeness.

輸出名稱仍為 `recent_partition_completeness`。Pass 僅表示受評估日期符合本地 coverage／status 規則與投球量 heuristic，不能證明來源完整。

- Dates must be within `metadata.pipeline_ranges` and strictly before today's **America/Los_Angeles** date. Aware datetimes are converted by instant; naive datetimes are interpreted as UTC. The timezone is fixed in code, not configurable through policy.
- Completed statuses are `Final`, `Game Over`, `Completed Early`. `Postponed` is ignored for unsettled detection; all other values, including NULL, are unsettled.
- Status evaluation retains `(game_pk, game_date, game_status)`; pitch joins deduplicate to `(game_pk, game_date)`. Coverage requires matching game IDs and `pitch.game_date = context.official_date`.
- The latest date containing completed or unsettled games is evaluated; postponed-only dates are skipped. At most 14 preceding such dates are considered, then dates without completed games, with missing same-date coverage, or with unsettled games are excluded. Filtering does not replenish the window. Retained dates are **eligible baseline dates**, not independently verified complete dates.
- The baseline is the median of daily pitches per completed game, requiring at least 7 eligible dates. It is recomputed from current DuckDB rows, independently of successful-run history.

- 日期必須位於 pipeline ranges，且嚴格早於洛杉磯今天。Aware datetime 依同一時刻轉換；naive datetime 明確視為 UTC。時區固定於程式，不是可調 policy。
- Completed 狀態為 Final、Game Over、Completed Early；Postponed 不造成 unsettled；其他值（包含 NULL）均為 unsettled。
- 狀態評估保留 game/date/status；join pitches 前去重至 game/date。Coverage 同時要求 game ID 與 official date 相符。
- 評估最新含 completed 或 unsettled games 的日期，略過 postponed-only 日期；最多取前 14 個同類日期，再排除無 completed games、coverage 不足或 unsettled 日期。篩除後不往更早日期補齊。留下的是 eligible baseline dates，並非經獨立驗證的完整日期。
- Baseline 為各日期「每場 completed game 平均投球數」的中位數，至少需要 7 個 eligible dates；由目前 DuckDB 重算，與成功 run 歷史基準分開。

Branches execute in this order / 分支依下列順序執行：

| Condition / 條件 | Status | Assessment |
| --- | --- | --- |
| No completed or unsettled dates / 無 completed 或 unsettled 日期 | bootstrap | Not emitted / 不輸出 |
| Completed game lacks same-date pitches / 已完賽場次無同日 pitches | error | Not emitted / 不輸出 |
| Evaluated date has unsettled games / 受評估日期含未定狀態 | attention | unknown_unsettled_date |
| Too few eligible baseline dates / eligible 日期不足 | attention | unknown_insufficient_baseline |
| Daily ratio outside 0.65–1.35, or minimum-game ratio below 0.65 / 日比例超界或最低單場比例過低 | attention | volume_anomaly |
| All applicable conditions satisfied / 通過適用條件 | pass | Not emitted / 不輸出 |

Diagnostics retain `ratio`, `minimum_game_ratio`, `baseline_median_pitches_per_game`, pitch counts and coverage. The minimum-game heuristic compares one game count with the median of daily per-game averages, not a calibrated distribution of individual games. There is no individual-game upper-bound check.

診斷保留日比例、最低單場比例、baseline median、投球數與 coverage。單場 heuristic 比較最低單場投球數與「各日每場平均」的中位數，並非經校準的單場分布；目前沒有單場上界檢查。

## Limits and review findings / 限制與審查結果

The evaluated date is reported as `latest_evaluated_date`. If it has no completed games, `latest_completed_date`, per-completed-game average and coverage ratio are NULL; active/unknown-only dates return attention even without completed history. With no completed or unsettled dates, bootstrap can still contribute to an overall pass. When unsettled games and missing completed-game coverage occur on the same date, the deterministic coverage error takes precedence.

`latest_evaluated_date` 記錄受評估日期；當日無 completed games 時，`latest_completed_date`、每場平均與 coverage ratio 為 NULL。只有 active／unknown 的日期即使無 completed history 也回傳 attention。完全沒有 completed 或 unsettled 日期時，bootstrap 仍可能讓整體為 pass。同一天同時有 unsettled 與 missing coverage 時，可確定的 coverage error 優先。

Nonzero but partially loaded games, uniformly truncated history, and games missing entirely from local context cannot be ruled out by pitch counts. An anomaly does not prove truncation or duplication. The separate [MLB source reconciler](SOURCE_RECONCILIATION.md) adds live schedule/play-by-play evidence at game and plate-appearance grain; its documented boundaries still apply. Global row-volume errors retain their existing severity and likewise do not establish a root cause.

非零但部分載入的場次、歷史一致性截斷、以及本地 context 完全遺漏的比賽，均無法僅靠 pitch counts 排除。獨立的 [MLB 來源對帳工具](SOURCE_RECONCILIATION.md)新增 game／plate-appearance grain 的即時 schedule／play-by-play 證據，但其文件中的限制仍然成立。Global row-volume error 保留既有嚴重性，同樣不能單獨證明根因。

## Run and inspect / 執行與查閱

```powershell
# Read-only source DuckDB; writes local observation history and JSON
.\.venv\Scripts\python.exe -m src.observability

# Quality gate plus coverage exports
.\.venv\Scripts\python.exe -m src.validate_data

# Observability tests and full Python suite
.\.venv\Scripts\python.exe -m unittest tests.test_observability -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Git-ignored `outputs/observability/` holds `history.sqlite`, per-attempt JSON and an atomically replaced `latest.json`. Only overall passing runs establish cross-run schema/row-volume baselines. Scope includes database path, mode, configured ranges and policy; changes start a new scope. SQLite serializes baseline selection and insertion. Concurrent JSON exports can finish out of order, so use SQLite sequence for history ordering. No external notification service is configured.

Git 排除的 outputs/observability 保存 SQLite 歷史、每次嘗試的 JSON 與原子替換的 latest.json。只有整體 pass 的 run 可成為跨 run schema／總筆數基準。Scope 包含資料庫路徑、mode、日期設定與 policy；更動會建立新 scope。SQLite 將基準選取與新增序列化；並行 JSON 匯出可能亂序，歷史應以 SQLite sequence 排序。目前沒有外部通知服務。

Review alerts before rerunning: verify dates/extraction logs for freshness, reconcile source/load evidence for volume anomalies, and inspect same-date game coverage for integrity failures. Attention still stops downstream execution; it expresses uncertainty rather than approval to publish.

重跑前先檢視 alert：freshness 核對日期與抽取紀錄；volume anomaly 核對來源／載入證據；integrity failure 檢查同日場次 coverage。Attention 仍停止下游，表達的是不確定性，並非允許發布。

## Evidence and resume wording / 證據與履歷描述

[Tests](../tests/test_observability.py) cover same-date coverage, deterministic-error precedence, baseline eligibility, insufficient history, mixed completed/unsettled dates, postponed games, duplicate terminal statuses, Los Angeles extraction/freshness boundaries, low/high volume anomalies, normal volume, persistence and recovery. On 2026-09-21, the Python suite reported 155 tests: 152 passed and 3 PostgreSQL integration tests skipped because no integration database was configured. These are project-wide counts, not 155 observability-specific tests.

[測試](../tests/test_observability.py)涵蓋同日 coverage、deterministic error 優先序、基準資格、歷史不足、completed／unsettled 混合日期、延賽、terminal 狀態重複、洛杉磯 extraction／freshness 日期邊界、高低投球量、正常投球量、持久化與恢復。2026-09-21 全專案 Python suite 共 155 項：152 通過，3 項因未設定 PostgreSQL integration database 跳過；不是 155 項 observability 專屬測試。

The 2026-09-20 real DuckDB smoke run read 1,355,356 pitch rows and passed 33 SQL checks. Recent partition passed (15/15 games covered; daily ratio 0.9961); overall status was attention because data through September 9 lagged the expected September 20 cutoff by 11 days. These are dated results, not a current freshness claim.

2026-09-20 真實 DuckDB smoke run 讀取 1,355,356 pitch rows，33 項 SQL 檢查通過；recent partition 通過（15/15 場 coverage、日比例 0.9961）。整體 attention 原因為資料停在 9 月 9 日，比預期 9 月 20 日落後 11 天。此為有日期的驗證紀錄，不代表目前新鮮度。

- Built a DuckDB observability gate with persistent audit history, same-date game coverage checks, eligible historical baselines, and timezone-aware partition evaluation; distinguished integrity failures from volume anomalies with 15 regression contract tests.
- 建置 DuckDB 可觀測性閘門，包含持久化稽核紀錄、同日場次 coverage、eligible 歷史基準與時區日期判定；以 15 項契約回歸測試驗證完整性錯誤與投球量異常的區分。
