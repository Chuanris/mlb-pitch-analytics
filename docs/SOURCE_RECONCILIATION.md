# MLB source reconciliation / MLB 上游來源對帳

This project can produce strong, dated source-to-target reconciliation evidence. It cannot prove that MLB's own systems are error-free, immutable, or independently audited.

本專案可產生有日期、可重現的來源至目的端對帳證據；但不能證明 MLB 自身系統絕無錯誤、資料永不修改，或已通過獨立稽核。

## Contract / 契約

`src.reconcile_mlb_source` independently re-fetches two official MLB endpoints instead of trusting the cached local game context:

`src.reconcile_mlb_source` 不信任本地已快取的 game context，而是重新讀取兩個 MLB 官方 endpoint：

- The regular-season schedule defines the expected set of games whose `abstractGameState` is `Final` on the requested official date.
- Each matching live game feed supplies plate appearances and events where `isPitch=true`.
- Local `silver.fact_game_context` must contain every official final game on the same date with a completed status.
- Local `silver.fact_pitch` must contain the same games and the same actual-pitch count for every `(game_pk, at_bat_number)`.
- Any missing or unexpected game, wrong-date load, missing or unexpected plate appearance, or plate-appearance pitch-count difference is an error.

- 例行賽 schedule 決定指定 official date 上 `abstractGameState=Final` 的預期場次集合。
- 每場 live game feed 提供 plate appearances 與 `isPitch=true` 的實際投球事件。
- 本地 `silver.fact_game_context` 必須在同一天具有每場官方 Final game，且狀態為 completed。
- 本地 `silver.fact_pitch` 必須具有相同場次，且每個 `(game_pk, at_bat_number)` 的實際投球數一致。
- 缺少或多出場次、日期錯置、缺少或多出 plate appearance，或單一 plate appearance 投球數不符，均為 error。

The comparison deliberately does not join MLB `pitchNumber` directly to Statcast `pitch_number`. Pitch-timer violations and other no-pitch events give those fields different numbering semantics. Per-plate-appearance actual-pitch counts preserve a common grain without pretending the raw identifiers are equivalent.

對帳刻意不直接連接 MLB `pitchNumber` 與 Statcast `pitch_number`。Pitch-timer violation 與其他 no-pitch 事件會讓兩欄位採用不同編號語意；以每個 plate appearance 的實際投球數比較，才能維持共同 grain，而不假裝原始識別碼完全等價。

## Run / 執行

```powershell
# Last locally loaded date; writes an ignored evidence file.
.\.venv\Scripts\python.exe -m src.reconcile_mlb_source `
  --date 2026-09-09 `
  --output outputs/observability/mlb-source-reconciliation-2026-09-09.json

# Expected current cutoff; returns nonzero while local data is missing.
.\.venv\Scripts\python.exe -m src.reconcile_mlb_source `
  --date 2026-09-20 `
  --output outputs/observability/mlb-source-reconciliation-2026-09-20.json
```

The command is read-only against DuckDB. It writes output only when `--output` is supplied. A source outage returns `attention / unknown_source_unavailable`; no official final games returns `attention / unknown_no_final_games`; a mismatch returns `error / source_mismatch`; exact reconciliation returns `pass / source_reconciled`.

此指令以唯讀方式開啟 DuckDB，只有提供 `--output` 才會寫入證據檔。官方來源無法存取時回傳 `attention / unknown_source_unavailable`；沒有官方完賽時回傳 `attention / unknown_no_final_games`；對帳不符為 `error / source_mismatch`；完全一致才是 `pass / source_reconciled`。

## Dated evidence / 有日期的證據

On 2026-09-21 Pacific time, a live reconciliation of official date **2026-09-09** passed:

- 15 official final games = 15 local completed context games = 15 local pitch games.
- 1,123 official plate appearances = 1,123 local plate appearances.
- 4,380 official pitch events = 4,380 local pitch rows.
- No game, date, plate-appearance, or pitch-count mismatch was found.
- The evidence JSON records SHA-256 digests for the schedule response and all 15 game feeds.

在 2026-09-21（Pacific time）即時對帳 official date **2026-09-09**，結果為 pass：

- 15 場官方 Final games = 15 場本地 completed context games = 15 場本地 pitch games。
- 1,123 個官方 plate appearances = 1,123 個本地 plate appearances。
- 4,380 個官方 pitch events = 4,380 筆本地 pitch rows。
- 未發現 game、date、plate appearance 或 pitch-count mismatch。
- 證據 JSON 保存 schedule response 與 15 個 game feeds 的 SHA-256 digest。

The same check for official date **2026-09-20** failed: MLB reported 15 final games while the local database contained zero context games and zero pitch games for that date. Therefore the repository has strong evidence that September 9 is reconciled, but it must **not** claim that the currently configured 2026 range is complete through September 20.

同一檢查套用於 official date **2026-09-20** 時失敗：MLB 有 15 場 Final games，本地資料庫在該日則有 0 場 context games 與 0 場 pitch games。因此，本專案可強力支持 9 月 9 日已完成對帳，但**不能**宣稱目前設定的 2026 範圍已完整至 9 月 20 日。

## What remains unknowable / 仍無法知道的部分

- Both reference endpoints are operated by MLB; agreement is source-to-target reconciliation, not an independent audit of MLB.
- MLB may correct historical schedule or play-by-play data after the check. Response hashes preserve what was observed at check time but do not make the upstream immutable.
- Per-plate-appearance counts prove count agreement at that grain. In theory, an omitted and an extra event within the same plate appearance could offset each other; event-level semantic reconciliation would require a separately governed cross-source identifier or additional event fingerprints.
- A passing single date does not establish season-wide completeness. Each claimed period must be reconciled, and current freshness must pass separately.

- 兩個參考 endpoint 都由 MLB 維運；一致代表 source-to-target reconciliation，而不是對 MLB 的獨立稽核。
- MLB 可能在檢查後修正歷史 schedule 或 play-by-play。Response hashes 保存檢查當下看到的內容，但無法讓上游資料不可變。
- 每個 plate appearance 的筆數一致可證明該 grain 的 count agreement；理論上，同一 plate appearance 內一筆遺漏與一筆多出可能互相抵銷。Event-level semantic reconciliation 需要另一個受治理的跨來源識別碼或更多 event fingerprints。
- 單日 pass 不代表整季完整；每個宣稱期間都必須對帳，且 current freshness 也必須另外通過。

## Resume-safe wording / 安全的履歷表述

- Implemented official MLB schedule and play-by-play reconciliation against DuckDB at game and plate-appearance grain; verified one 15-game slate across 1,123 plate appearances and 4,380 pitch events, while explicitly blocking current-range completeness claims when newer official games were absent locally.
- 以 MLB 官方 schedule 與 play-by-play 對 DuckDB 執行 game／plate-appearance grain 對帳；驗證一個 15 場比賽日的 1,123 個 plate appearances 與 4,380 個 pitch events，並在本地缺少較新官方場次時阻止宣稱 current-range 完整。
