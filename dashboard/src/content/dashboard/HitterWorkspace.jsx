import React, { useEffect, useMemo, useState } from 'react';
import { DataComponent, DataTable, useDataApp } from '../../data-app-public.jsx';
import { CATEGORIES, PRIORITIES, finite, isFresh, openGames, rankHitters, replacementDelta, combinedAverage, hitterSignals, matchHitterNames } from './hitter-analysis.js';
import './hitters.css';

const POOL_KEY='mlb-fantasy-hitter-pool-v1';
const poolValues=['unknown','available','roster','watch','unavailable'];
const dec=(v,n=1)=>finite(v)?Number(v).toFixed(n):'—';
const pct=v=>finite(v)?`${(v*100).toFixed(1)}%`:'—';
const signed=(v,n=1)=>finite(v)?`${v>0?'+':''}${Number(v).toFixed(n)}`:'—';
function savedPool(){try {
  const value=JSON.parse(localStorage.getItem(POOL_KEY)||'{}');
  return Object.fromEntries(Object.entries(value||{}).filter(([id,status])=>/^\d+$/.test(id)&&poolValues.includes(status)));
}catch{return {};}}

export default function HitterWorkspace({language}) {
  const {reviewedRows}=useDataApp();
  const rows=useMemo(()=>reviewedRows('fantasy_hitters'),[reviewedRows]);
  const games=useMemo(()=>[...new Map(rows.flatMap(row=>JSON.parse(row.schedule_json||'[]'))
    .map(g=>[`${g.game_pk}:${g.team}`,g])).values()],[rows]);
  const metadata=useMemo(()=>reviewedRows('hitter_metadata')[0],[reviewedRows]);
  const evaluation=useMemo(()=>reviewedRows('hitter_validation'),[reviewedRows]);
  const zh=language==='zh-TW', t=(en,cn)=>zh?cn:en;
  const [now,setNow]=useState(Date.now);
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer);},[]);
  const liveGames=useMemo(()=>openGames(games,now),[games,now]);
  const days=useMemo(()=>[...new Set(liveGames.map(g=>g.game_date))].sort(),[liveGames]);
  const [chosenDays,setChosenDays]=useState(null);
  const dates=chosenDays===null?days:days.filter(day=>chosenDays.includes(day));
  const [priority,setPriority]=useState('balanced'), [weights,setWeights]=useState(PRIORITIES.balanced);
  const [position,setPosition]=useState('all'), [scope,setScope]=useState('all'), [search,setSearch]=useState('');
  const [targetAvg,setTargetAvg]=useState('.260'), [rateMode,setRateMode]=useState('season');
  const [pool,setPool]=useState(savedPool), [storageError,setStorageError]=useState(false);
  const [selectedId,setSelectedId]=useState(''), [incumbentId,setIncumbentId]=useState('');
  const [teamHits,setTeamHits]=useState(''), [teamAB,setTeamAB]=useState('');
  const [importNames,setImportNames]=useState(''), [importStatus,setImportStatus]=useState('available');
  const importMatch=useMemo(()=>matchHitterNames(importNames,rows),[importNames,rows]);
  const targetValid=finite(targetAvg)&&Number(targetAvg)>=0&&Number(targetAvg)<=1;
  const plans=useMemo(()=>rankHitters(rows,games,{dates,weights,targetAvg:targetValid?Number(targetAvg):null,now,rateMode}),
    [rows,games,dates.join(','),weights,targetAvg,targetValid,now,rateMode]);
  const fresh=isFresh(metadata,now);
  const statusOf=row=>pool[row.batter_id]||'unknown';
  const labelStatus=value=>({unknown:t('Not classified','未分類'),available:t('Available','可加入'),roster:t('My roster','我的球員'),watch:t('Watchlist','觀察名單'),unavailable:t('Unavailable','不可加入')}[value]);
  const filtered=plans.filter(row=>(position==='all'||(position==='OF'?['OF','LF','CF','RF'].includes(row.position):row.position===position))
    && (scope==='all'||statusOf(row)===scope) && row.batter_name.toLowerCase().includes(search.trim().toLowerCase()));
  const shortlist=fresh&&targetValid?filtered.filter(r=>r.priority_score!==null&&statusOf(r)!=='unavailable').slice(0,5):[];
  const selected=plans.find(r=>String(r.batter_id)===selectedId)||shortlist[0]||filtered[0];
  const incumbent=plans.find(r=>String(r.batter_id)===incumbentId&&r.batter_id!==selected?.batter_id);
  const delta=selected&&incumbent?replacementDelta(selected,incumbent):null;
  const options=[...plans].sort((a,b)=>a.batter_name.localeCompare(b.batter_name));
  const localDate=value=>new Intl.DateTimeFormat(zh?'zh-TW':'en-US',{month:'short',day:'numeric',weekday:'short',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));
  const mark=(id,value)=>{
    const next={...pool,[id]:value};setPool(next);
    try{localStorage.setItem(POOL_KEY,JSON.stringify(next));setStorageError(false);}catch{setStorageError(true);}
  };
  const signalText=(code,row)=>({
    inactive:t('Not on a fetched MLB active roster. Do not treat this as a lineup option.','未列入本次擷取的 MLB 現役名單，不作先發建議。'),
    limited:t('Outside the automatic shortlist: check playing time, sample size and source coverage.','未達自動推薦門檻：請檢查出賽量、樣本與來源覆蓋率。'),
    short_season:t(`Only ${row.pa_season} season PA; treat the pace as a fragile small-sample scenario.`, `球季只有 ${row.pa_season} PA；速率仍受小樣本影響，請保守解讀。`),
    role_up:t(`Opportunity rising: PA per team game ${dec(row.pa_per_team_game_prev7)} → ${dec(row.pa_per_team_game_7)}.`,
      `打席機會增加：球隊每場 PA ${dec(row.pa_per_team_game_prev7)} → ${dec(row.pa_per_team_game_7)}。`),
    role_down:t(`Playing-time risk: PA per team game ${dec(row.pa_per_team_game_prev7)} → ${dec(row.pa_per_team_game_7)}.`,
      `出賽量下降：球隊每場 PA ${dec(row.pa_per_team_game_prev7)} → ${dec(row.pa_per_team_game_7)}，先查打線。`),
    contact_up:t(`Hard contact improved ${pct(row.hard_hit_prev14)} → ${pct(row.hard_hit_14)} without a large K-rate rise. Watch, not proof of a breakout.`,
      `強擊球率 ${pct(row.hard_hit_prev14)} → ${pct(row.hard_hit_14)}，K% 未明顯增加；值得追蹤，尚非突破證明。`),
    under_contact:t(`Covered-AB AVG ${dec(row.covered_avg_30,3)} trails xBA ${dec(row.covered_xba_30,3)}. Investigate contact quality; a rebound is not owed.`,
      `同覆蓋打數 AVG ${dec(row.covered_avg_30,3)} 低於 xBA ${dec(row.covered_xba_30,3)}；檢查擊球品質，不代表必然反彈。`),
    over_contact:t(`Covered-AB AVG ${dec(row.covered_avg_30,3)} exceeds xBA ${dec(row.covered_xba_30,3)}. Do not extrapolate the hot streak.`,
      `同覆蓋打數 AVG ${dec(row.covered_avg_30,3)} 高於 xBA ${dec(row.covered_xba_30,3)}，不要直接外推近期熱度。`),
    steal_activity:t(`Actual 30-day steals: ${row.sb_30}; caught stealing: ${row.cs_30}. Attempts, not running speed alone.`,
      `30 日實際盜壘 ${row.sb_30}、失敗 ${row.cs_30}；以跑壘行動佐證，不只看速度。`),
    steady:t('No gated change signal. The absence of an alert is not evidence of safety.','未觸發變化訊號；沒有提醒不代表沒有風險。'),
  }[code]);
  if(!rows.length)return <section className="mlb-hitters"><p>{t('Hitter research requires the full pipeline and official hitting statistics. Sample mode intentionally leaves it empty.','打者研究需要完整資料流程與官方打擊統計；Sample 模式刻意不提供此資料。')}</p></section>;

  return <section className="mlb-hitters" aria-label={t('Daily 5x5 hitter decisions','每日 5×5 打者決策')}>
    <p className="hitters-intro">{t('Fill a real lineup gap. Spend the roster spot on the categories you need.','先找真正的先發空缺，再把名額用在你缺的類別。')}</p>
    <p className="hitters-note">{t('Statistics through','統計截至')} {metadata?.data_through} · {t('Daily lineups · R / HR / RBI / SB / AVG','每日調整 · R／HR／RBI／SB／AVG')}<br/>
      {t('Roster / schedule checked','名單／賽程查詢')} {metadata?.roster_fetched_at_utc?.slice(0,16).replace('T',' ')} / {metadata?.schedule_fetched_at_utc?.slice(0,16).replace('T',' ')} UTC</p>
    {!fresh&&<p role="status" className="hitters-alert">{t('Roster or schedule evidence is over 24 hours old or unavailable. Automatic shortlists are paused; refresh the full daily pipeline before acting. Historical evidence remains available.','名單或賽程超過 24 小時或不可用，暫停自動候選建議；請先更新完整每日流程。歷史證據仍可查閱。')}</p>}
    <fieldset className="hitters-days"><legend>{t('Which days have an open lineup slot?','哪些日期有可用的先發空位？')}</legend>
      <p className="hitters-note">{t('All dates selected initially. Uncheck full days; no roster or lineup is inferred. Dates follow the MLB schedule.','預設全選；取消已排滿的日期。系統不推測你的陣容；日期依 MLB 賽程。')}</p>
      <div>{days.map(day=><label key={day}><input type="checkbox" checked={dates.includes(day)} onChange={()=>setChosenDays(dates.includes(day)?dates.filter(d=>d!==day):[...dates,day])}/>{localDate(day)}</label>)}</div>
      {!days.length&&<p>{t('No unstarted, timed games remain in this schedule snapshot.','這份賽程已沒有尚未開打且時間確定的比賽。')}</p>}
    </fieldset>
    <div className="hitters-controls">
      <label>{t('Category need','類別需求')}<select id="hitter-priority" value={priority} onChange={e=>{setPriority(e.target.value);if(PRIORITIES[e.target.value])setWeights(PRIORITIES[e.target.value]);}}>
        {Object.keys(PRIORITIES).map(key=><option key={key} value={key}>{({balanced:t('Balanced 5x5','均衡 5×5'),power:t('HR + RBI','補 HR／RBI'),speed:t('Chase steals','追 SB'),average:t('Protect AVG','保護 AVG'),runs:t('Add runs','補 R')})[key]}</option>)}
        <option value="custom">{t('Custom weights','自訂權重')}</option>
      </select></label>
      <label>{t('MLB primary position','MLB 主要守位')}<select id="hitter-position" value={position} onChange={e=>setPosition(e.target.value)}>
        {['all','C','1B','2B','3B','SS','OF','DH'].map(p=><option key={p} value={p}>{p==='all'?t('All positions','所有守位'):p}</option>)}
      </select></label>
      <label>{t('Personal player pool','個人球員池')}<select id="hitter-pool-filter" value={scope} onChange={e=>setScope(e.target.value)}>
        <option value="all">{t('All research candidates','全部研究候選')}</option>{poolValues.map(p=><option key={p} value={p}>{labelStatus(p)}</option>)}
      </select></label>
      <label>{t('Find a hitter','搜尋打者')}<input id="hitter-search" type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder={t('Player name','球員英文姓名')}/></label>
    </div>
    <details className="hitters-settings"><summary>{t('Adjust category weights and pace assumptions','調整類別權重與估算假設')}</summary>
      <div className="hitters-controls">{CATEGORIES.map(key=><label key={key}>{key.toUpperCase()}<input aria-label={`${key.toUpperCase()} weight`} type="number" min="0" max="5" step="1" value={weights[key]} onChange={e=>{setPriority('custom');setWeights({...weights,[key]:Math.min(5,Math.max(0,Number(e.target.value)||0))});}}/></label>)}</div>
      <div className="hitters-controls"><label>{t('Target AVG (not a league average)','目標 AVG（非聯盟平均）')}<input id="hitter-target-avg" type="number" min="0" max="1" step="0.005" value={targetAvg} onChange={e=>setTargetAvg(e.target.value)}/></label>
        <label>{t('Rate baseline','速率基準')}<select id="hitter-rate-mode" value={rateMode} onChange={e=>setRateMode(e.target.value)}><option value="season">{t('Season rate · default','球季累積速率 · 預設')}</option><option value="recent">{t('Smoothed 30-day rate · scenario','近 30 日平滑速率 · 情境')}</option></select></label></div>
      <p className="hitters-note">{t('Weighted z-scores prioritize the fixed eligible population for your selected dates, before search or pool filters. They are not win probabilities, standings gains or fantasy points. AVG uses excess hits over your target, not a simple average of player averages.','權重套用於所選日期的合格球員標準化值，參照群體不受搜尋／球員池篩選影響。它不是勝率、排名提升或 Fantasy 分數；AVG 使用相對目標的超額安打，不平均球員打擊率。')}</p>
    </details>
    <details className="hitters-settings"><summary>{t('Paste your available hitters or roster','貼上自由球員或自己的陣容')}</summary>
      <p className="hitters-note">{t('One full player name per line. Exact name matches only; unmatched or ambiguous names are not assigned. Existing labels for other players remain. These labels stay in this browser.','每行一位完整英文姓名。只接受明確姓名匹配；未匹配或同名歧義不會套用。其他球員既有標記保留；名單只存此瀏覽器。')}</p>
      <label>{t('Player names','球員姓名')}<textarea id="hitter-import-names" rows="4" value={importNames} onChange={e=>setImportNames(e.target.value)} /></label>
      <div className="hitters-controls"><label>{t('Apply label','套用標記')}<select value={importStatus} onChange={e=>setImportStatus(e.target.value)}>{poolValues.map(p=><option key={p} value={p}>{labelStatus(p)}</option>)}</select></label>
        <button id="hitter-import-apply" type="button" disabled={!importMatch.matched.length} onClick={()=>{
          const next={...pool,...Object.fromEntries(importMatch.matched.map(id=>[id,importStatus]))};setPool(next);setScope(importStatus);
          try{localStorage.setItem(POOL_KEY,JSON.stringify(next));setStorageError(false);}catch{setStorageError(true);}
        }}>{t(`Apply ${importMatch.matched.length} matches`, `套用 ${importMatch.matched.length} 位匹配球員`)}</button></div>
      {importMatch.unresolved.length>0&&<p role="status" className="hitters-note">{t('Not matched','未匹配')}: {importMatch.unresolved.join(' · ')}</p>}
    </details>
    {!targetValid&&<p role="alert">{t('Enter a target AVG between 0 and 1.','目標 AVG 請輸入 0 至 1。')}</p>}
    <DataComponent variant="card" id="hitters-board" queryId="fantasy_hitters"
      sourceRows={shortlist.map(r=>rows.find(s=>s.batter_id===r.batter_id))} displayRows={shortlist.map(({selected_games,...r})=>r)} kind="table"
      title={t('Your daily shortlist','你的每日候選清單')} description={t('Planning paces on selected open dates. Confirm fantasy availability, eligibility and the batting lineup before adding.','僅估算所選空缺日的產量；加入前確認 Fantasy 可用狀態、守位資格與先發打線。')}>
      {shortlist.length?<ol className="hitters-shortlist">{shortlist.map((row,index)=><li key={row.batter_id} data-hitter-id={row.batter_id}>
        <div className="hitters-player"><span className="hitters-rank">{index+1}</span><div><button type="button" onClick={()=>setSelectedId(String(row.batter_id))}>{row.batter_name}</button><p>{row.team} · {row.position} · {labelStatus(statusOf(row))}</p></div></div>
        <dl><div><dt>{t('Open-date games','空缺日場數')}</dt><dd>{row.planned_games}</dd></div><div><dt>{t('PA pace','PA 估值')}</dt><dd>{dec(row.planned_pa)}</dd></div><div><dt>HR / SB</dt><dd>{dec(row.planned_hr)} / {dec(row.planned_sb)}</dd></div><div><dt>{t('AVG excess H','AVG 超額 H')}</dt><dd>{signed(row.planned_avg_impact)}</dd></div></dl>
        <p className="hitters-reason">{t('Selected-date pace','所選日期估值')}: {dec(row.planned_r)} R · {dec(row.planned_rbi)} RBI · AVG {dec(row.planned_avg,3)}. {signalText(hitterSignals(row).find(s=>s==='role_down')||hitterSignals(row)[0],row)}</p>
      </li>)}</ol>:<p role="status">{t('No automatic shortlist for these settings. Select an open day and a nonzero category weight, or broaden your filters. Players without enough evidence remain in the lookup below.','目前設定沒有自動候選。請選空缺日與非零類別權重，或放寬篩選；證據不足的球員仍可在下方查閱。')}</p>}
    </DataComponent>
    <div className="hitters-controls hitters-player-picker"><label>{t('Inspect hitter','檢視打者')}<select id="hitter-detail-select" value={selected?.batter_id||''} onChange={e=>setSelectedId(e.target.value)}>{options.map(row=><option key={row.batter_id} value={row.batter_id}>{row.batter_name} · {row.team}</option>)}</select></label>
      {selected&&<label>{t('Mark availability in your league','標記你聯盟的可用狀態')}<select id="hitter-mark-pool" value={statusOf(selected)} onChange={e=>mark(selected.batter_id,e.target.value)}>{poolValues.map(p=><option key={p} value={p}>{labelStatus(p)}</option>)}</select></label>}
    </div>
    {storageError&&<p role="status">{t('Browser storage is unavailable. Labels work for this visit only.','瀏覽器無法保存設定；標記只在這次瀏覽有效。')}</p>}
    {selected&&<>
      <DataComponent variant="card" id="hitters-detail" queryId="fantasy_hitters" sourceRows={rows.filter(r=>r.batter_id===selected.batter_id)} kind="table"
        title={`${selected.batter_name} · ${t('Evidence before action','行動前的證據')}`}>
        <ul className="hitters-signals">{hitterSignals(selected).map(code=><li key={code}>{signalText(code,selected)}</li>)}</ul>
        <p className="hitters-note">{t('30-day official totals','30 日官方實績')}: {selected.pa_30} PA · {selected.r_30} R · {selected.hr_30} HR · {selected.rbi_30} RBI · {selected.sb_30} SB · AVG {dec(selected.avg_30,3)}<br/>
          {t('Statcast PA / official PA','Statcast／官方 PA')}: {selected.statcast_pa_30??0} / {selected.pa_30} · {t('Last observed game','最後觀測出賽')}: {selected.last_seen||'—'}</p>
        <DataTable rows={[
          {metric:t('Official PA','官方 PA'),prev:dec(selected.pa_prev14,0),recent:dec(selected.pa_14,0),month:dec(selected.pa_30,0)},
          {metric:'K / PA',prev:pct(selected.k_rate_prev14),recent:pct(selected.k_rate_14),month:pct(selected.k_rate_30)},
          {metric:t('Hard-hit / measured BBE','強擊球／有效初速 BBE'),prev:pct(selected.hard_hit_prev14),recent:pct(selected.hard_hit_14),month:pct(selected.hard_hit_30)},
          {metric:t('Measured BBE','有效初速 BBE'),prev:dec(selected.measured_bbe_prev14,0),recent:dec(selected.measured_bbe_14,0),month:dec(selected.measured_bbe_30,0)},
          {metric:t('Barrel / classified BBE','Barrel／可分類 BBE'),prev:pct(selected.barrel_prev14),recent:pct(selected.barrel_14),month:pct(selected.barrel_30)},
          {metric:t('Whiff / swings','揮空／揮棒'),prev:pct(selected.whiff_prev14),recent:pct(selected.whiff_14),month:pct(selected.whiff_30)},
          {metric:t('Chase / known out-of-zone pitches','追打／已知帶外球'),prev:pct(selected.chase_prev14),recent:pct(selected.chase_14),month:pct(selected.chase_30)},
        ]} columns={[{field:'metric',label:t('Metric','指標')},{field:'prev',label:t('Prior 14d','前 14 日')},{field:'recent',label:t('Latest 14d','近 14 日')},{field:'month',label:t('Latest 30d','近 30 日')}]} />
        <p className="hitters-note">{t('Covered-AB xBA / actual AVG','同覆蓋打數 xBA／實際 AVG')}: {dec(selected.covered_xba_30,3)} / {dec(selected.covered_avg_30,3)} · {selected.covered_ab_30??0}/{selected.statcast_ab_30??0} AB. {t('Missing tracking stays unknown; this is not a future batting-average forecast.','缺少追蹤保留未知；這不是未來打擊率預測。')}</p>
      </DataComponent>
      <DataComponent variant="card" id="hitters-impact" queryId="fantasy_hitters" sourceRows={rows.filter(r=>[selected.batter_id,incumbent?.batter_id].includes(r.batter_id))} kind="table" title={t('What does this roster spot gain?','這個名額實際換來什麼？')}>
        <label className="hitters-compare-label">{t('Compare with another hitter on the same open dates','與另一位打者比較相同空缺日')}<select id="hitter-incumbent" value={incumbent?.batter_id||''} onChange={e=>setIncumbentId(e.target.value)}><option value="">{t('Choose a replacement baseline','選擇替換基準')}</option>{options.filter(r=>r.batter_id!==selected.batter_id).map(row=><option key={row.batter_id} value={row.batter_id}>{row.batter_name} · {labelStatus(statusOf(row))}</option>)}</select></label>
        <p className="hitters-note">{t('These are planning estimates, not calibrated projections. Same selected dates for both players; no automatic add/drop or position eligibility check.','以下為計畫估值，不是已校準預測；兩位球員使用相同所選日期，不自動加退球員或判斷守位資格。')}</p>
        <DataTable rows={[
          {metric:t('Planned PA','PA 估值'),candidate:dec(selected.planned_pa),baseline:dec(incumbent?.planned_pa),delta:signed(delta?.pa)},
          ...['r','hr','rbi','sb'].map(k=>({metric:k.toUpperCase(),candidate:dec(selected[`planned_${k}`]),baseline:dec(incumbent?.[`planned_${k}`]),delta:signed(delta?.[k])})),
          {metric:`AVG ${t('excess hits vs','超額安打，相對')} ${targetAvg}`,candidate:signed(selected.planned_avg_impact),baseline:signed(incumbent?.planned_avg_impact),delta:signed(delta?.avg_impact)}
        ]} columns={[{field:'metric',label:t('Category','類別')},{field:'candidate',label:selected.batter_name},{field:'baseline',label:incumbent?.batter_name||t('Baseline','基準')},{field:'delta',label:t('Change','增減')}]} />
        <details className="hitters-settings"><summary>{t('Calculate your team AVG impact','計算球隊 AVG 影響')}</summary><p className="hitters-note">{t('Enter team hits and AB before either future option. Compare adding each player to that same base; already accumulated stats are never removed.','輸入尚未加上任一未來方案的球隊 H 與 AB；比較兩種方案加到同一基底，已累積實績不會被扣除。')}</p><div className="hitters-controls">
          <label>{t('Team hits','球隊 H')}<input id="hitter-team-h" type="number" min="0" value={teamHits} onChange={e=>setTeamHits(e.target.value)}/></label>
          <label>{t('Team at-bats','球隊 AB')}<input id="hitter-team-ab" type="number" min="1" value={teamAB} onChange={e=>setTeamAB(e.target.value)}/></label></div>
          <p aria-live="polite">{selected.batter_name}: {dec(combinedAverage(teamHits,teamAB,selected),4)}{incumbent?` · ${incumbent.batter_name}: ${dec(combinedAverage(teamHits,teamAB,incumbent),4)}`:''}</p>
        </details>
      </DataComponent>
      <DataComponent variant="card" id="hitters-schedule" queryId="hitter_schedule" sourceRows={selected.selected_games} kind="table" title={`${selected.batter_name} · ${t('Games on your open dates','空缺日賽程')}`}>
        <p className="hitters-note">{t('Unannounced starters remain unknown. Pitcher handedness is context, not a small-sample matchup boost. No confirmed batting-lineup feed.','未公布先發保留未知；投手慣用手僅供情境判讀，不以小樣本對戰加分。尚未接入已確認打線。')}</p>
        <DataTable rows={selected.selected_games.map(g=>({...g,date_display:localDate(g.game_date),site:g.home?t('Home','主場'):t('Away','客場')}))} columns={[{field:'date_display',label:t('Date','日期')},{field:'opponent',label:t('Opponent','對手')},{field:'site',label:t('Site','主客場')},{field:'pitcher_name',label:t('Probable pitcher','預定先發')},{field:'pitcher_hand',label:t('Throws','投手慣用手')}]} />
        <p className="hitters-note">{t('30d contact-only xwOBA by pitcher hand (shown at 25+ measured BBE)','近 30 日對左右投的接觸後 xwOBA（至少 25 筆有效 BBE 才顯示）')}: L {selected.con_L_n_30>=25?dec(selected.con_L_xwoba_30,3):'—'} ({selected.con_L_n_30??0} BBE) · R {selected.con_R_n_30>=25?dec(selected.con_R_xwoba_30,3):'—'} ({selected.con_R_n_30??0} BBE)</p>
      </DataComponent>
    </>}
    <DataComponent variant="card" id="hitters-table" queryId="fantasy_hitters" sourceRows={rows.filter(r=>filtered.some(p=>p.batter_id===r.batter_id))} displayRows={filtered.map(r=>({batter_name:r.batter_name,team:r.team,position:r.position,pa:r.pa_30,r:r.r_30,hr:r.hr_30,rbi:r.rbi_30,sb:r.sb_30,avg:dec(r.avg_30,3),status:labelStatus(statusOf(r))}))} kind="table" title={t('Official 30-day results · all matching hitters','官方近 30 日實績 · 所有符合篩選的打者')}>
      <DataTable rows={filtered.map(r=>({batter_name:r.batter_name,team:r.team,position:r.position,pa:r.pa_30,r:r.r_30,hr:r.hr_30,rbi:r.rbi_30,sb:r.sb_30,avg:dec(r.avg_30,3),status:labelStatus(statusOf(r))}))} columns={['batter_name','team','position','pa','r','hr','rbi','sb','avg','status'].map(field=>({field,label:({batter_name:t('Hitter','打者'),team:t('Team','球隊'),position:t('Position','守位'),status:t('Your label','你的標記')})[field]||field.toUpperCase()}))} pageSize={10}/>
    </DataComponent>
    <DataComponent variant="card" id="hitters-validation" queryId="hitter_validation" sourceRows={evaluation} kind="table" title={t('Does recency actually help?','近期加權真的有幫助嗎？')}>
      <p className="hitters-note">{t('Three chronological weeks; candidates chosen only from prior statistics. Errors use actual future PA/AB to isolate rate quality. This does not validate playing time, lineup choices or waiver gains. Lower MAE is better; H checks hits, not team AVG.','使用三個跨時間週期，候選只依當時已知統計選出；以實際未來 PA／AB 隔離速率誤差。此檢查不驗證出賽量、排陣或補人收益。MAE 越低越好；H 評估安打數，非球隊 AVG。')}</p>
      <DataTable rows={evaluation.map(r=>({...r,season:dec(r.season_mae,3),recent:dec(r.smoothed_mae,3),change:signed(r.smoothed_mae-r.season_mae,3)}))} columns={[{field:'metric',label:t('Category','類別')},{field:'player_weeks',label:t('Player-weeks','球員週')},{field:'season',label:t('Season MAE','球季 MAE')},{field:'recent',label:t('Smoothed MAE','近期平滑 MAE')},{field:'change',label:t('Error change','誤差增減')}]} />
      <p className="hitters-note">{evaluation[0]?.windows||t('No chronological rate diagnostic has been generated yet.','尚未產生跨時間速率檢查。')}</p>
    </DataComponent>
    <DataComponent id="hitters-method" queryId="hitter_metadata" sourceRows={metadata?[metadata]:[]} kind="text" title={t('How to use this responsibly','如何解讀建議')}>
      <p className="hitters-note">{t('Automatic candidates require an active MLB roster listing, 100 season PA, 30 recent PA, at least 5 observed current-team games in 14 days, at least 2 PA per team game, a game in the last 4 data days, and 95–105% Statcast/official PA reconciliation. These are screening heuristics, not statistical confidence levels. Primary position is not your platform’s eligibility.','自動候選需列入 MLB 現役名單、球季 100 PA、近 30 日 30 PA、近 14 日現球隊至少 5 場、球隊每場至少 2 PA、最近 4 個資料日內出賽，以及 Statcast／官方 PA 比率 95–105%。這些是篩選規則，不是統計信心水準。主要守位不等於平台守位資格。')}</p>
      <p className="hitters-note">{t('Planned PA = your selected unstarted games × current-team 14d PA per team game, capped at 5 per game. Counts use season rates by default. The optional smoothed rate uses a non-overlapping season prior. Park, weather, injury, batting order and opponent quality are not forecast adjustments. Check actual lineups before lock.','PA 估值＝所選未開打場數 × 現球隊近 14 日每場 PA（每場上限 5）。產量預設用球季速率；可選平滑版使用不重疊的球季先驗。球場、天氣、傷勢、棒次及對手能力尚未納入預測調整；鎖定前務必確認實際打線。')}</p>
    </DataComponent>
  </section>;
}
