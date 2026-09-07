import React, { useMemo, useState } from "react";
import { DataComponent, DataTable, useDataApp } from "../../data-app-public.jsx";

function numeric(value) { return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)); }
const decimal = (value, digits = 1) => numeric(value) ? Number(value).toFixed(digits) : "—";
const percent = value => numeric(value) ? `${(Number(value) * 100).toFixed(1)}%` : "—";

export function comparisonRows(selected, chinese = false) {
  const metric = (en, zh, read) => ({ metric: chinese ? zh : en,
    ...Object.fromEntries(selected.map((row, index) => [`pitcher_${index}`, read(row)])) });
  return [
    metric("Team", "球隊", row => row.pitcher_team || "—"),
    metric("Observed window", "歷史觀測期間", row => row.window_start ? `${row.window_start} – ${row.window_end}` : "—"),
    metric("Recorded pitches", "近期投球數", row => decimal(row.pitches, 0)),
    metric("K minus BB rate", "三振率－保送率", row => percent(row.k_minus_bb_rate)),
    metric("Expected whiff / swing", "每次揮棒的預期揮空率", row => percent(row.expected_whiff_rate)),
    metric("Observed hard-hit rate", "實際被強擊球率", row => percent(row.hard_hit_rate_allowed)),
    metric("Measured batted balls", "有效擊球初速樣本", row => decimal(row.measured_batted_balls, 0)),
    metric("Average velocity (mph)", "平均球速（mph）", row => decimal(row.avg_velocity)),
    metric("Next probable start", "下一場預定先發", row => row.game_date ? `${row.game_date} · ${row.opponent_team}` : (chinese ? "尚無確認場次" : "Not confirmed")),
    metric("Predicted strikeouts", "預測三振數", row => decimal(row.predicted_k)),
    metric("Empirical prediction range", "經驗預測區間", row => numeric(row.lower_k) && numeric(row.upper_k) ? `${row.lower_k}–${row.upper_k}` : "—"),
    metric("Prior starts used (max 5)", "採用的過去先發場數（最多 5）", row => decimal(row.prior_starts, 0)),
    metric("Pregame data through", "賽前特徵資料截止日", row => row.feature_data_through || "—"),
  ];
}

export default function PitcherComparison({ language }) {
  const { reviewedRows } = useDataApp();
  const rows = useMemo(() => reviewedRows("pitcher_comparison"), [reviewedRows]);
  const forecasts = useMemo(() => reviewedRows("starter_forecasts"), [reviewedRows]);
  const evaluation = useMemo(() => reviewedRows("starter_forecast_evaluation"), [reviewedRows]);
  const history = useMemo(() => reviewedRows("starter_forecast_history"), [reviewedRows]);
  const monitor = useMemo(() => reviewedRows("starter_live_monitor"), [reviewedRows]);
  const zh = language === "zh-TW";
  const text = (en, chinese) => zh ? chinese : en;
  const [ids, setIds] = useState(() => {
    const next = rows.filter(row => numeric(row.predicted_k))
      .sort((a,b) => String(a.game_date).localeCompare(String(b.game_date)) || b.predicted_k-a.predicted_k);
    const initial = (next.length ? next : rows).slice(0,2).map(row=>String(row.pitcher_id));
    return [initial[0] || "", initial[1] || "", ""];
  });
  const candidates = useMemo(() => [...rows].sort((a,b) => a.pitcher_name.localeCompare(b.pitcher_name)), [rows]);
  const selected = ids.map(id=>rows.find(row=>String(row.pitcher_id)===id)).filter(Boolean);
  const displayRows = comparisonRows(selected, zh);
  const selectedModel = evaluation.find(row=>row.is_selected);
  const modelName = key => ({
    league_mean:text("League mean", "聯盟先發平均"),
    recent_starts:text("Recent starts, adjusted for small samples", "近期先發平均（小樣本調整）"),
    workload_opponent:text("Workload and opponent", "工作量與對手調整"),
  }[key] || key);
  const evaluationRows = evaluation.map(row=>({...row, model_label:modelName(row.model),
    selected_label:row.is_selected ? text("Selected on validation", "由驗證期選出") : "—",
    selection_mae_display:decimal(row.selection_mae,2), mae_display:decimal(row.mae,2), rmse_display:decimal(row.rmse,2)}));
  const forecastRows = forecasts.map(row=>({...row, predicted_display:decimal(row.predicted_k),
    interval_display:`${row.lower_k}–${row.upper_k}`, starts_display:String(row.prior_starts),
    sample_display:row.prior_starts<3 ? text("Limited history", "先發歷史較少") : text("3+ prior starts", "已有至少 3 場先發")}));
  const observed = history.filter(row=>row.outcome_status === "observed");
  const historyRows = history.slice(-100).map(row=>({...row,
    predicted_display:decimal(row.predicted_k), actual_display:decimal(row.actual_k,0),
    recorded_display:row.generated_at_utc ? `${row.generated_at_utc.slice(0,16).replace("T"," ")} UTC` : "—",
    status_display:({pending:text("Pending", "待比賽完成"), observed:text("Observed", "已有結果"),
      did_not_start:text("Did not start", "未擔任先發"), excluded_after_actual_start:text("Excluded: recorded after start", "排除：紀錄晚於開賽")})[row.outcome_status] || row.outcome_status}));

  return <section className="mlb-comparison" aria-label={text("Pitcher comparison and starter forecasts", "投手比較與先發預測")}>
    <div className="mlb-comparison-selectors">
      {ids.map((id,index)=><label key={index} htmlFor={`compare-pitcher-${index}`}>
        <span>{text(`Pitcher ${index+1}`, `投手 ${index+1}`)}</span>
        <select id={`compare-pitcher-${index}`} value={rows.some(row=>String(row.pitcher_id)===id) ? id : ""}
          onChange={event=>setIds(current=>current.map((value,i)=>i===index ? event.target.value : value))}>
          <option value="">{text("Choose a pitcher", "選擇投手")}</option>
          {candidates.map(row=><option key={row.pitcher_id} value={String(row.pitcher_id)} disabled={ids.some((value,i)=>i!==index && value===String(row.pitcher_id))}>
            {row.pitcher_name} · {row.pitcher_team}
          </option>)}
        </select>
      </label>)}
    </div>
    <DataComponent variant="card" id="pitcher-comparison" queryId="pitcher_comparison" kind="table"
      title={text("Compare evidence before choosing", "選人前，並排比較證據")} sourceRows={selected} displayRows={displayRows}
      description={text("Historical skill and next-start forecasts are separate. A missing start or measurement stays unknown.", "歷史球質與下一場預測分開呈現；尚未確認先發或缺少測量時，保留為未知。") }>
      {selected.length ? <DataTable rows={displayRows} columns={[{field:"metric",label:text("Metric","指標")},
        ...selected.map((row,index)=>({field:`pitcher_${index}`,label:row.pitcher_name}))]} />
        : <p>{text("Select two or three pitchers. Full-mode data is required.", "請選擇兩至三位投手；此功能需要完整模式資料。")}</p>}
    </DataComponent>
    <DataComponent variant="card" id="starter-forecast-table" queryId="starter_forecasts" kind="table"
      title={text("Next-start strikeout baseline", "下一場三振基準預測")} sourceRows={forecasts} displayRows={forecastRows}
      description={text("Confirmed probable starters only. Forecasts use prior-day data and exclude current-game measurements; starter changes and workload limits remain uncertain.", "僅列已確認的預定先發。預測只使用前一日以前資料，不使用當場測量；先發異動與投球限制仍有不確定性。") }>
      <p className="mlb-comparison-note">{selectedModel
        ? text(`Selected model: ${modelName(selectedModel.model)}. Intended interval coverage: 80%; measured fixed-test coverage: ${percent(selectedModel.interval_coverage)}.`,
          `採用模型：${modelName(selectedModel.model)}。區間目標覆蓋率 80%；固定測試期實際覆蓋率 ${percent(selectedModel.interval_coverage)}。`)
        : text("Forecast evaluation is not available in sample mode.", "Sample 模式沒有預測評估。")}</p>
      <DataTable rows={forecastRows} columns={[
        {field:"pitcher_name",label:text("Pitcher","投手")},{field:"game_date",label:text("Start date","先發日期")},
        {field:"opponent_team",label:text("Opponent","對手")},{field:"predicted_display",label:text("Expected K","預期三振")},
        {field:"interval_display",label:text("Range","區間")},{field:"sample_display",label:text("Starting history","先發樣本")},
      ]} />
    </DataComponent>
    <DataComponent variant="card" id="starter-forecast-evaluation" queryId="starter_forecast_evaluation" kind="table"
      title={text("Does the baseline beat a simple average?", "是否優於簡單平均？")} sourceRows={evaluation} displayRows={evaluationRows}
      description={text("Selection uses early validation, intervals use its later dates, and the final test is separate. Retrospective observed starters include openers and short outings; this is not a replay of historical probable announcements.", "早期驗證資料選模型、較晚驗證資料估計區間，最後才評估固定測試期。回測包含開局投手與短先發，並非歷史預定先發公告的重播。") }>
      {selectedModel && <p className="mlb-comparison-note">{selectedModel.test_start} – {selectedModel.test_end} · {selectedModel.rows} {text("starts; MAE measures average absolute error in strikeouts.", "場先發；MAE 代表平均相差多少次三振。")}</p>}
      <DataTable rows={evaluationRows} columns={[
        {field:"model_label",label:text("Baseline","基準模型")},{field:"selected_label",label:text("Use","採用狀態")},
        {field:"selection_mae_display",label:text("Validation MAE","驗證 MAE")},
        {field:"mae_display",label:text("Test MAE","測試 MAE")},{field:"rmse_display",label:text("Test RMSE","測試 RMSE")},
      ]} />
    </DataComponent>
    <DataComponent variant="card" id="starter-live-monitor" queryId="starter_live_monitor" kind="table"
      title={text("Live forecast performance", "實際賽前預測表現")} sourceRows={monitor}
      description={text("First archived forecasts only, separated by model version. Pending and excluded outcomes do not count as zero. Positive bias means overprediction; fewer than 30 outcomes is a limited sample, and larger samples still do not prove reliability.", "只統計首次存檔的實際賽前預測，依模型版本分開。待完成與排除紀錄不算零；正偏差表示高估。少於 30 筆標為樣本不足，達到門檻也不代表已證明可靠。") }>
      <DataTable rows={monitor.map(row=>({...row,
        mae_display:decimal(row.mae,2), bias_display:decimal(row.bias,2),
        coverage_display:percent(row.interval_coverage),
        status_display:row.status === "awaiting_outcomes" ? text("Awaiting outcomes", "尚無賽後結果") : row.status === "limited_sample" ? text("Limited sample", "樣本不足") : text("Descriptive only", "僅供描述觀察")
      }))} columns={[
        {field:"model_version",label:text("Model version","模型版本")},
        {field:"data_through",label:text("Outcomes through","賽果資料截止")},
        {field:"observed",label:text("Scored","有效結果")},{field:"pending",label:text("Pending","待完成")},
        {field:"excluded",label:text("Excluded","排除")},{field:"invalid_outcomes",label:text("Invalid outcomes","無效結果")},
        {field:"mae_display",label:"MAE"},{field:"bias_display",label:text("Bias","偏差")},
        {field:"coverage_display",label:text("Coverage","區間覆蓋率")},
        {field:"interval_rows",label:text("Interval sample","區間樣本")},
        {field:"status_display",label:text("Evidence status","證據狀態")},
      ]} />
    </DataComponent>
    <DataComponent variant="card" id="starter-forecast-history" queryId="starter_forecast_history" kind="table"
      title={text("Recorded before first pitch", "賽前留下紀錄，賽後核對")} sourceRows={history} displayRows={historyRows}
      description={text("First recorded forecast for each game and pitcher; canceled or changed starters are not scored as zero strikeouts. Historical backtest rows are never inserted as live forecasts.", "每場比賽、每位投手保留第一筆賽前預測；更換先發不會被當成零三振。歷史回測不會冒充實際賽前紀錄。") }>
      <p className="mlb-comparison-note">{observed.length
        ? text(`${observed.length} forecasts have observed outcomes.`, `已有 ${observed.length} 筆預測可核對實際結果。`)
        : text("No completed live forecast outcomes yet. Results appear after a future daily update.", "目前尚無完成的實際賽前預測；比賽結束後，後續每日更新會補上結果。")}</p>
      <DataTable rows={historyRows} columns={[
        {field:"pitcher_name",label:text("Pitcher","投手")},{field:"game_date",label:text("Game date","比賽日期")},
        {field:"recorded_display",label:text("Recorded before start","賽前紀錄時間")},
        {field:"predicted_display",label:text("Predicted K","預測三振")},{field:"actual_display",label:text("Actual K","實際三振")},
        {field:"status_display",label:text("Status","狀態")},
      ]} />
    </DataComponent>
  </section>;
}
