# MLB source reconciliation / MLB 上游來源對帳

This project can produce strong, dated source-to-target reconciliation evidence. It cannot prove that MLB's own systems are error-free, immutable, or independently audited.

本專案可產生有日期、可重現的來源至目的端對帳證據；但不能證明 MLB 自身系統絕無錯誤、資料永不修改，或已通過獨立稽核。

## Contract / 契約

`src.reconcile_mlb_source` independently re-fetches two official MLB endpoints instead of trusting the cached local game context:

`src.reconcile_mlb_source` 不信任本地已快取的 game context，而是重新讀取兩個 MLB 官方 endpoint：

- The regular-season schedule defines the expected set of games whose `abstractGameState` is `Final` on the requested official date.
- Each matching live game feed supplies all plays, the subset of plate appearances containing an `isPitch=true` event, and the individual `isPitch=true` events.
- Local `silver.fact_game_context` must contain every official final game on the same date with a completed status.
- Local `silver.fact_pitch` must contain the same games and the same actual-pitch count for every `(game_pk, at_bat_number)`.
- Any missing or unexpected game, wrong-date load, missing or unexpected plate appearance, or plate-appearance pitch-count difference is an error.

- 例行賽 schedule 決定指定 official date 上 `abstractGameState=Final` 的預期場次集合。
- 每場 live game feed 提供全部 plays、至少包含一個 `isPitch=true` event 的 plate appearances，以及每個 `isPitch=true` 的實際投球事件。
- 本地 `silver.fact_game_context` 必須在同一天具有每場官方 Final game，且狀態為 completed。
- 本地 `silver.fact_pitch` 必須具有相同場次，且每個 `(game_pk, at_bat_number)` 的實際投球數一致。
- 缺少或多出場次、日期錯置、缺少或多出 plate appearance，或單一 plate appearance 投球數不符，均為 error。

The comparison deliberately does not join MLB `pitchNumber` directly to Statcast `pitch_number`. Pitch-timer violations and other no-pitch events give those fields different numbering semantics. Per-plate-appearance actual-pitch counts preserve a common grain without pretending the raw identifiers are equivalent.

對帳刻意不直接連接 MLB `pitchNumber` 與 Statcast `pitch_number`。Pitch-timer violation 與其他 no-pitch 事件會讓兩欄位採用不同編號語意；以每個 plate appearance 的實際投球數比較，才能維持共同 grain，而不假裝原始識別碼完全等價。

## Run / 執行

```powershell
# Inspect one official date; writes an ignored diagnostic file.
.\.venv\Scripts\python.exe -m src.reconcile_mlb_source `
  --date 2026-09-20 `
  --output outputs/observability/mlb-source-reconciliation-2026-09-20.json

# Rebuild the compact range manifest retained in Git.
.\.venv\Scripts\python.exe -m src.build_mlb_source_audit `
  --start-date 2026-09-09 `
  --end-date 2026-09-20 `
  --output evidence/mlb-source-audit/2026-09-09_2026-09-20.json
```

Both commands are read-only against DuckDB. The single-date command writes output only when `--output` is supplied. The range command preserves every daily result in one manifest and still writes it when the aggregate exit code is nonzero. A source outage returns `attention / unknown_source_unavailable`; no official final games returns `attention / unknown_no_final_games`; a mismatch returns `error / source_mismatch`; exact reconciliation returns `pass / source_reconciled`.

兩個指令都以唯讀方式開啟 DuckDB。單日指令只有在提供 `--output` 時才寫入檔案；range 指令將每日結果保存在同一份 manifest，即使整體 exit code 非零仍會寫出。官方來源無法存取時回傳 `attention / unknown_source_unavailable`；沒有官方完賽時回傳 `attention / unknown_no_final_games`；對帳不符為 `error / source_mismatch`；完全一致才是 `pass / source_reconciled`。

## Dated evidence / 有日期的證據

The versioned [September 9–20 audit manifest](../evidence/mlb-source-audit/2026-09-09_2026-09-20.json) was generated at 2026-09-24 02:50 UTC from a local snapshot ending on September 22. Across 12 official dates it records:

- 159 official final games and 12,110 all plays.
- 12,087 pitch-bearing plate appearances and 46,843 official pitch events.
- 46,843 Raw pitch-proxy rows; each of the 12 daily proxy totals matched the official event total.
- 46,821 Silver pitch rows, 22 fewer than the official count.
- Seven `pass / source_reconciled` dates and five `error / source_mismatch` dates.
- Local regular-season Raw and Silver snapshots of 1,408,305 and 1,403,065 rows, respectively, both ending on September 22.

The manifest's aggregate result is `error / audit_has_errors`. That is intentional: the artifact preserves the five Silver discrepancies while showing the narrower Raw proxy agreement. It must **not** be cited as proof of season-wide or event-semantic completeness.

版本化的 [9 月 9–20 日稽核 manifest](../evidence/mlb-source-audit/2026-09-09_2026-09-20.json) 於 2026-09-24 02:50 UTC 產生，本機快照資料至 9 月 22 日。12 個 official dates 的結果如下：

- 159 場官方 Final games 與 12,110 個全部 plays。
- 12,087 個含投球事件的 plate appearances 與 46,843 個官方 pitch events。
- 46,843 筆 Raw pitch-proxy rows；12 天的每日 proxy 總數都與官方 event 總數一致。
- 46,821 筆 Silver pitch rows，比官方數少 22 筆。
- 七天為 `pass / source_reconciled`，五天為 `error / source_mismatch`。
- 本機 regular-season Raw 與 Silver 快照分別為 1,408,305 與 1,403,065 筆，兩者資料日期都至 9 月 22 日。

Manifest 的整體結果是 `error / audit_has_errors`。這是刻意保留的結果：artifact 同時呈現五個 Silver 差異與較窄的 Raw proxy 一致性，**不能**被引用為整季或 event-semantic completeness 的證明。

## What remains unknowable / 仍無法知道的部分

- Both reference endpoints are operated by MLB; agreement is source-to-target reconciliation, not an independent audit of MLB.
- MLB may correct historical schedule or play-by-play data after the check. Response hashes preserve what was observed at check time but do not make the upstream immutable.
- Per-plate-appearance counts prove count agreement at that grain. In theory, an omitted and an extra event within the same plate appearance could offset each other; event-level semantic reconciliation would require a separately governed cross-source identifier or additional event fingerprints.
- A passing date or bounded range does not establish season-wide completeness. Each claimed period must be reconciled, and current freshness must pass separately.

- 兩個參考 endpoint 都由 MLB 維運；一致代表 source-to-target reconciliation，而不是對 MLB 的獨立稽核。
- MLB 可能在檢查後修正歷史 schedule 或 play-by-play。Response hashes 保存檢查當下看到的內容，但無法讓上游資料不可變。
- 每個 plate appearance 的筆數一致可證明該 grain 的 count agreement；理論上，同一 plate appearance 內一筆遺漏與一筆多出可能互相抵銷。Event-level semantic reconciliation 需要另一個受治理的跨來源識別碼或更多 event fingerprints。
- 單日或有限日期範圍的 pass 不代表整季完整；每個宣稱期間都必須對帳，且 current freshness 也必須另外通過。

## Resume-safe wording / 安全的履歷表述

- Built a versioned official MLB schedule/live-feed audit against DuckDB at game and plate-appearance grain; checked 159 final games and 46,843 pitch events across 12 dates, matched the documented Raw proxy on all 12, and surfaced a 22-row Silver gap instead of claiming season-wide completeness.
- 建立版本化的 MLB 官方 schedule／live-feed 稽核，以 game 與 plate-appearance grain 對帳 DuckDB；在 12 天檢查 159 場 Final games 與 46,843 個 pitch events，12 天的 Raw proxy 都一致，並明確揭露 Silver 少 22 筆，而非宣稱整季完整。
