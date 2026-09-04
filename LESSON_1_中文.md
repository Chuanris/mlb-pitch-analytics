# 第一課：看懂資料管線、資料庫與Excel分母

這一課的目標不是背公式，而是能回答三個問題：

1. 一筆逐球資料如何從Baseball Savant走到Excel和Tableau？
2. 每一張資料表的一列代表什麼？
3. 為什麼Whiff Rate與Chase Rate不能直接除以全部投球數？

## 1. 先執行小型資料管線

在專案資料夾開啟Terminal：

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py --mode sample
```

成功時會看到：

- raw資料：9,450列
- silver逐球事實表：9,412列
- 33場比賽
- 251位投手
- 10項資料品質檢查全部PASS

原始列比silver少，是因為silver只保留2025例行賽、有效球種與完整逐球識別欄位，再依`pitch_id`去除重複列。

## 2. 理解Bronze、Silver、Gold

### Bronze

`bronze.raw_statcast`盡量保留來源欄位，不在這層改變指標定義。當下游結果不合理時，可以回到這裡追查。

### Silver

`silver.fact_pitch`是一球一列，建立：

- `pitch_id`
- `pitcher_team`
- `count_state`
- `in_zone_flag`
- `swing_flag`
- `whiff_flag`
- `chase_flag`
- `batted_ball_flag`
- `hard_hit_flag`
- `result_group`

這些欄位只定義一次，Excel、Tableau和SQL都重複使用同一版本。

### Gold

Gold層針對使用情境聚合資料：

- `pitcher_pitch_type_summary`
- `count_strategy_summary`
- `pitcher_month_summary`
- `tableau_pitch_detail`

這讓Dashboard不用每次重新掃描所有原始欄位。

## 3. 開啟Notebook

開啟`notebooks/01_pipeline_and_sql_tutorial.ipynb`，依序執行所有cell。重點不是複製SQL，而是看懂：

- `COUNT(DISTINCT ...)`如何驗證資料粒度
- `GROUP BY`如何產生球種比較
- window function如何計算占比或組內排名
- `NULLIF`如何避免分母為零
- quality gate為什麼要早於Dashboard refresh

## 4. 開啟Excel

開啟`outputs/MLB_Excel_Lesson_1.xlsx`。

### Pitch Sample

先找到兩列相同`game_pk-at_bat_number`、不同`pitch_number`的紀錄。這能確認資料粒度是一球，不是一個打席或一場比賽。

### Excel Lesson 1

逐一點選KPI儲存格並閱讀公式：

- `Swing Rate = Swings / All Pitches`
- `Whiff Rate = Whiffs / Swings`
- `Chase Rate = Chases / Out-of-Zone Pitches`
- `Hard-Hit Rate = Hard Hits / Batted-Ball Events`

如果把Whiff Rate除以全部投球數，就會把沒有揮棒的球也放進分母，衡量到的就不再是「揮棒時揮空的比例」。

## 5. 自己建立第一張PivotTable

1. 到`Pitch Sample`任一儲存格。
2. 選擇`Insert > PivotTable > From Table/Range`。
3. 放到New Worksheet。
4. Rows放`pitch_name`。
5. Values放`pitch_id`，設定為Count。
6. Values再放`release_speed`，設定為Average並顯示一位小數。
7. 將Pitch Count由大到小排序。
8. 加入`pitcher_team`和`batter_stand`作為Filters。

完成後，結果應與`Excel Lesson 1`的球種數量及平均球速一致。

## 6. 第一課可以描述的觀察

只限這三天樣本：

- 4-Seam Fastball占32.8%，是最常見球種。
- 樣本整體Swing Rate為48.2%，Whiff Rate為25.7%。
- Two Strikes情境的Chase Rate為40.3%，高於First Pitch的17.7%。
- Knuckle Curve的Whiff Rate很高，但只有147球；不能只看rate就宣稱它是最佳球種。

面試表達必須說「在這個三天樣本中觀察到」，不能把短期關聯說成完整球季結論或因果關係。

## 完成本課的標準

- 能畫出Bronze、Silver、Gold之間的資料流。
- 能解釋`pitch_id`為什麼唯一。
- 能不看答案說出四個rate的分母。
- 能自己重建PitchTable並與公式表核對。
- 能說出至少三項會讓pipeline停止發布的品質錯誤。
