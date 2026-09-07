# Daily 5×5 hitter decisions / 每日 5×5 打者決策

[Live dashboard](https://chuanris.github.io/mlb-pitch-analytics/) · [Operations](OPERATIONS.md) · [Implementation](../src/build_fantasy_hitters.py)

## English

### Start from the roster decision

The Hitters workspace targets **R, HR, RBI, SB and AVG with daily lineup changes**. A good hitter does not automatically make a good addition: the player must be available, fit your league's eligibility, have a useful game on a day you can use them, and help categories worth pursuing.

Use the workspace in this order:

1. Select dates with an actual open lineup slot. Uncheck days already covered by better options.
2. Choose a category need or set individual weights. A zero weight means that category does not contribute to the priority score.
3. Paste available-player names, one full name per line, or mark individual players. Names are matched exactly after case/accent normalization; ambiguous names are skipped. Nothing connects to or changes your fantasy account.
4. Review the shortlist's games, PA pace, category contributions and evidence flags. This is a research shortlist; unclassified players are not claimed to be on waivers.
5. Select your existing alternative in the replacement comparison. Both options use the same dates. Check the batting lineup and platform eligibility before lock.

### Three layers, kept separate

| Layer | What it measures | What decision it supports |
| --- | --- | --- |
| Opportunity | Unstarted scheduled games on selected open dates; recent PA per **team** game | Is the player likely to provide useful volume, including bench days? |
| Category contribution | Rate-based R / HR / RBI / SB paces and AVG excess hits | Does this option address the category shortage and justify the roster spot? |
| Evidence and risk | Official outcomes, contact quality, changes in opportunity, sample sizes and tracking coverage | Is the current story supported, or driven by a short hot streak or reduced role? |

There is no ownership percentage, platform eligibility feed or confirmed batting-lineup feed. MLB primary position is a lookup aid only. Active MLB status is necessary for the automatic shortlist, but does not guarantee a start.

### Counts and denominators

- Official MLB `byDateRange` hitting totals supply R, HR, RBI, SB, H, AB, PA, BB, K and caught stealing for season, 7-day, 14-day, 30-day and prior-14-day windows. The prior 14-day period does not overlap the current 14-day period.
- Statcast is deduplicated by pitch and then by completed plate appearance. Automatic/untracked terminal events are retained; `truncated_pa` is excluded. Names come from official player IDs, not the pitcher's `player_name` field or a text description.
- Hard-hit rate uses balls with nonmissing exit velocity as the denominator; Barrel rate uses balls with a nonmissing Statcast launch-speed/angle classification. Classification `6` is a Barrel.
- Chase rate divides swings outside the zone by pitches with a **known** out-of-zone location. Missing zone is not treated as outside the zone. Whiff rate divides misses by swings.
- The covered-AB xBA comparison uses the same at-bats on both sides: AB with a hit-probability estimate, plus strikeouts with zero expected hits. The interface shows covered AB and total Statcast AB. It is not the player's full official AVG or a calibrated future AVG forecast.
- Left/right contact-only xwOBA is shown only with at least 25 measured BBE in that split. It excludes walks and strikeouts and is **not** overall xwOBA. It does not multiply forecasts or turn small batter-versus-pitcher samples into matchup advantages.

Field definitions: [Baseball Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs). Official statistical endpoints, roster URLs and retrieval times are recorded in `outputs/hitters/manifest.json`; the diagnostic's separate retrieval evidence is in `outputs/hitters/evaluation_manifest.json`.

### Planning equations

The default is intentionally simple:

```text
Planned PA = selected unstarted team games × min(5, last14 current-team PA / team games)
Planned R, HR, RBI, SB = planned PA × season count / season PA
Planned AB = planned PA × season AB / season PA
Planned H = planned AB × season H / season AB
AVG excess H = planned H − target AVG × planned AB
```

PA per team game includes games in which the hitter had no PA. Current-team evidence avoids inflating a traded player's opportunity using plate appearances for their old club. The cap of 5 PA/game is a planning heuristic. Doubleheaders count as separate games; this may overstate volume if a player starts only one. Games already started and games with TBD times are excluded from selectable opportunities.

For an optional recency scenario, each rate uses a non-overlapping prior:

```text
Prior rate = (pre-30-day season count + 200 × league rate) / (pre-30-day season PA + 200)
Smoothed rate = (last30 count + 100 × prior rate) / (last30 PA + 100)
```

H uses AB instead of PA. These constants are smoothing choices, not established stabilization points. The displayed chronological diagnostic does not establish that recency is superior; season rates remain the default. Neither mode is a calibrated projection system.

Category priority is the weighted mean of z-scores for the four planned counting categories and AVG excess hits. The comparison population is all eligible hitters with remaining games on the selected dates, **before** position, search or personal-pool filtering. A positive score is not standings gain or win probability. Without league standings, opponents and replacement-level inputs, such claims would be unsupported.

### Replacement and ratio impact

Replacement deltas subtract the existing alternative's future contribution from the candidate's, using the same selected dates. They do not remove already-earned statistics. For AVG, compare the two alternatives against the same supplied team base:

```text
AVG with candidate = (team H + candidate planned H) / (team AB + candidate planned AB)
AVG with alternative = (team H + alternative planned H) / (team AB + alternative planned AB)
```

Empty or invalid team counts remain unknown. The initial `.260` target is editable user planning context, not a fetched league average.

### Evidence gates and insights

Automatic candidates require all of: an active MLB listing, at least 100 season PA, 30 PA in the last 30 days, five observed current-team games in 14 days, two PA per team game, an observed game in the last four data days, and Statcast/official PA reconciliation between 95% and 105%. Players outside this screen remain searchable. These rules control recommendation scope; they do not prove reliability or exclude every injured player.

- **Opportunity rising/falling:** a change of at least 0.8 PA per team game between non-overlapping seven-day periods, with at least three team games in each. A decline prompts a lineup/role check.
- **Improved contact:** at least 20 measured BBE and 30 official PA in each 14-day period; hard-hit rate rises at least 10 percentage points while K rate rises no more than 3 points. This is a watch signal, not proof of a breakout.
- **Results versus contact:** a covered-AB AVG/xBA gap of at least .040, with at least 50 covered AB, 90% AB coverage and passing PA reconciliation. It flags a question to investigate; expected statistics do not guarantee a rebound or collapse.
- **Steal activity:** at least three actual steals in 30 days, displayed beside caught stealing. Sprint speed alone is not used as a steal projection.
- **Short season sample:** fewer than 200 season PA gets a separate caution even if the player meets the minimum shortlist screen.

No alert does not mean low risk. Park, weather, lineup position, injuries and opponent skill are not modeled adjustments.

### What the chronological check proves

`--evaluate` uses three separate seven-day windows ending before or at the statistical cutoff. Each origin selects candidates using only prior season PA ≥100 and prior-30-day PA ≥30. It compares season and smoothed rates against the next week's official counts, conditional on **observed future PA/AB**, omitting zero-future-PA players.

This isolates rate errors. It does not test future playing time, injury detection, availability, full roster decisions, standings gain or profit. The same hitter may appear in several windows, so player-weeks are not independent players. MAE differences are descriptive and are not significance tests. No model is automatically selected from these test results.

The diagnostic is retained across daily refreshes with its explicit dates; run `--evaluate` again after changing the method or when a new review is desired. Normal daily updates refresh player evidence, roster and schedule without rerunning this diagnostic.

```powershell
# Refresh official hitter evidence and the chronological diagnostic
.\.venv\Scripts\python.exe -m src.build_fantasy_hitters --evaluate
.\.venv\Scripts\python.exe -m src.build_dashboard_snapshot
```

Roster or schedule retrieval older than 24 hours pauses automatic shortlists. Rebuilding HTML does not make source evidence fresher. Historical evidence and labeled planning comparisons remain available.

## 繁體中文

### 從陣容決策出發

打者決策頁專為 **R、HR、RBI、SB、AVG 五類別，且每日可調整先發** 設計。好打者不一定是好補人：他必須可加入、符合你聯盟的守位資格、在你有空位的日期出賽，並且補足值得追逐的類別。

建議操作順序：

1. 勾選真正有先發空位的日期，取消已由更好選項排滿的日期。
2. 選擇類別需求，或自訂個別權重；零代表該類別不參與排序。
3. 每行貼上一位自由球員的完整姓名，或逐一標記。只接受正規化大小寫／重音後的明確匹配；同名歧義會跳過。不連接或操作 Fantasy 帳戶。
4. 檢查候選的場數、PA 估值、類別貢獻與證據提醒。未分類球員不代表自由球員。
5. 選擇現有替代人選，比較相同日期的增減，並在鎖定前確認實際打線與平台守位資格。

### 分開看三層資訊

| 層次 | 衡量什麼 | 支援的決策 |
| --- | --- | --- |
| 出賽機會 | 所選空缺日尚未開打場數、近期每個球隊比賽的 PA | 是否能提供有效出賽量，包含坐板凳日？ |
| 類別貢獻 | R／HR／RBI／SB 速率估值，以及相對 AVG 目標的超額安打 | 是否補足缺口、值得使用名額？ |
| 證據與風險 | 官方實績、擊球品質、出賽量變化、樣本與追蹤覆蓋率 | 近期故事是否可信，或只是短期熱度／角色縮減？ |

目前沒有平台持有率、守位資格或已確認先發打線來源。MLB 主要守位僅供查找；MLB 現役狀態不保證今天先發。

### 統計與分母

- R、HR、RBI、SB、H、AB、PA、BB、K、盜壘失敗採 MLB 官方 `byDateRange`，提供球季、7 日、14 日、30 日及不重疊前 14 日視窗。
- Statcast 先依球去重，再依完成的打席去重，保留自動／未追蹤的打席結束事件，排除 `truncated_pa`。姓名透過官方球員 ID 取得，不從投手姓名欄或文字描述猜測。
- 強擊球率分母是有初速數值的擊球；Barrel 率分母是有 Statcast 速度／角度分類的擊球，分類 `6` 表示 Barrel。
- 追打率分母只含已知位置且在帶外的球；缺少位置不算帶外。揮空率分母為揮棒。
- 同覆蓋打數的 xBA 比較，兩側使用相同 AB：有安打機率估計的打數，加上預期安打為零的三振。頁面列出覆蓋 AB 與全部 Statcast AB；這不等於官方完整 AVG，也不是已校準的未來打擊率。
- 對左右投的接觸後 xwOBA，分組至少 25 筆有效 BBE 才顯示；不含保送／三振，因此不是整體 xwOBA，也不拿來乘上預測或將小樣本對戰包裝成優勢。

欄位來源：[Baseball Savant CSV 文件](https://baseballsavant.mlb.com/csv-docs)。統計、名單與查詢時間保存在 `outputs/hitters/manifest.json`，跨時間檢查另存於 `outputs/hitters/evaluation_manifest.json`。

### 計畫估值公式

```text
PA 估值 = 所選未開打場數 × min(5, 現球隊近14日 PA / 球隊場數)
R、HR、RBI、SB 估值 = PA 估值 × 球季該項數量 / 球季 PA
AB 估值 = PA 估值 × 球季 AB / 球季 PA
H 估值 = AB 估值 × 球季 H / 球季 AB
AVG 超額 H = H 估值 − 目標 AVG × AB 估值
```

球隊每場 PA 包含該打者沒有打席的比賽；轉隊者只用現球隊的出賽證據，避免混入舊隊打席。每場 5 PA 上限是估算規則；雙重賽算兩場，若只先發其中一場會高估機會。已開打或時間未定的比賽不列入可選機會。

選用的近期情境採不重疊先驗：

```text
先驗速率 = (近30日之前的球季數量 + 200 × 聯盟速率) / (先前球季 PA + 200)
平滑速率 = (近30日數量 + 100 × 先驗速率) / (近30日 PA + 100)
```

H 的分母改用 AB。100／200 是平滑設定，不是經證明的穩定樣本量。跨時間檢查沒有證明近期加權全面較好，因此預設保留球季速率；兩種都不是已校準的預測系統。

優先順序為四個累積類別估值與 AVG 超額安打之 z-score 加權平均。參照群體是所選日期有比賽的全部合格打者，不受守位、搜尋與個人球員池篩選影響。它不是積分榜增益或勝率；缺少聯盟排名、對手與替代水準時，不做這種承諾。

### 替換成本與打擊率

替換增減使用相同空缺日，把候選的未來估值減去現有替代人的未來估值，不扣除已累積實績。AVG 將兩種選項加到相同球隊基底：

```text
採用候選的 AVG = (球隊 H + 候選 H 估值) / (球隊 AB + 候選 AB 估值)
採用替代人的 AVG = (球隊 H + 替代人 H 估值) / (球隊 AB + 替代人 AB 估值)
```

空白或不合理的球隊數值保留未知。預設 `.260` 是可修改的目標，不是查得的聯盟平均。

### 證據門檻與 insight

自動候選須同時符合：MLB 現役、球季至少 100 PA、近 30 日 30 PA、近 14 日現球隊至少 5 場、每個球隊比賽至少 2 PA、最近 4 個資料日內出賽，以及 Statcast／官方 PA 比率 95–105%。未達門檻仍可查閱；這些規則不保證可靠，也無法排除所有傷勢。

- **機會增加／減少：**兩個不重疊 7 日視窗各至少 3 場球隊比賽，每場 PA 變化至少 0.8；下降時先查打線與角色。
- **擊球改善：**兩個 14 日視窗各至少 20 筆有效初速 BBE 與 30 官方 PA，強擊球率增加至少 10 個百分點，K% 上升不超過 3 個百分點；這是追蹤訊號，不是突破證明。
- **結果與擊球落差：**同覆蓋 AB 的 AVG／xBA 相差至少 .040，需至少 50 覆蓋 AB、90% AB 覆蓋率與合格 PA 對帳。只標記待研究問題，不保證反彈或崩跌。
- **盜壘行動：**30 日至少 3 次實際盜壘，旁列盜壘失敗；不單用跑速推估盜壘。
- **球季小樣本：**不足 200 PA 另行提醒，即使已達自動候選最低門檻。

沒有提醒不代表低風險；球場、天氣、棒次、傷勢與對手能力尚未納入預測調整。

### 跨時間檢查的界線

`--evaluate` 使用截至統計截止日內的三個獨立 7 日視窗；每個起點只依當時球季 PA ≥100、近 30 日 PA ≥30 選候選。以實際未來 PA／AB 比較兩種速率與下一週官方實績，排除未來零 PA 者。

它隔離速率誤差，未驗證未來出賽量、傷勢識別、平台可用性、完整排陣、排名提升或獲利。同一球員可出現多週，因此球員週不是獨立球員；MAE 差異是描述性結果，不是顯著性檢定，也不會自動據此換模型。

每日更新會保留檢查結果及其明確日期；方法改變或需要新評估時，再執行 `--evaluate`。一般每日流程只更新球員證據、名單與賽程。

```powershell
# 更新官方打者資料並執行跨時間檢查
.\.venv\Scripts\python.exe -m src.build_fantasy_hitters --evaluate
.\.venv\Scripts\python.exe -m src.build_dashboard_snapshot
```

名單或賽程查詢超過 24 小時，會暫停自動候選；只重建 HTML 不會讓來源變新。歷史證據與明確標示的情境比較仍可使用。
