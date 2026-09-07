export const CATEGORIES = ['r', 'hr', 'rbi', 'sb', 'avg'];
export const PRIORITIES = {
  balanced: {r:1,hr:1,rbi:1,sb:1,avg:1},
  power: {r:1,hr:3,rbi:2,sb:0,avg:1},
  speed: {r:1,hr:0,rbi:0,sb:3,avg:1},
  average: {r:1,hr:0,rbi:0,sb:0,avg:3},
  runs: {r:3,hr:1,rbi:0,sb:1,avg:1},
};
export const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
export function isFresh(metadata, now = Date.now()) {
  return ['schedule_fetched_at_utc','roster_fetched_at_utc'].every(key => {
    const age = now - Date.parse(metadata?.[key]);
    return Number.isFinite(age) && age >= -300000 && age <= 24*60*60*1000;
  });
}
export function openGames(games, now = Date.now()) {
  // TBD games cannot safely become today's lineup recommendation.
  return games.filter(g => !g.time_tbd && Date.parse(g.starts_at_utc) > now);
}
export function planHitter(row, games, dates, targetAvg = .260, now = Date.now(), rateMode = 'season') {
  const selected = openGames(games, now).filter(g => g.team === row.team && dates.includes(g.game_date));
  const valid = Boolean(row.eligible) && finite(row.pa_per_team_game_14) && row.pa_per_team_game_14 >= 0;
  const pa = valid ? Math.min(5, row.pa_per_team_game_14) * selected.length : null;
  const plan = { ...row, planned_games:selected.length, planned_pa:pa, selected_games:selected };
  const prefix = rateMode === 'recent' ? 'pace_' : 'season_rate_';
  for (const key of ['r','hr','rbi','sb','ab']) plan[`planned_${key}`] = pa !== null && finite(row[`${prefix}${key}`]) ? pa*row[`${prefix}${key}`] : null;
  plan.planned_h = plan.planned_ab !== null && finite(row[`${prefix}h`]) ? plan.planned_ab*row[`${prefix}h`] : null;
  plan.planned_avg = plan.planned_ab > 0 ? plan.planned_h/plan.planned_ab : null;
  plan.planned_avg_impact = finite(targetAvg) && targetAvg>=0 && targetAvg<=1 && plan.planned_h !== null && plan.planned_ab !== null ? plan.planned_h-targetAvg*plan.planned_ab : null;
  return plan;
}
export function rankHitters(rows, games, {dates, weights=PRIORITIES.balanced, targetAvg=.260, now=Date.now(), rateMode='season'} = {}) {
  const plans = rows.map(row=>planHitter(row,games,dates ?? [],targetAvg,now,rateMode));
  const pool = plans.filter(r=>r.eligible && r.planned_games>0 && CATEGORIES.every(k=>finite(r[k==='avg'?'planned_avg_impact':`planned_${k}`])));
  const z = {};
  for (const key of CATEGORIES) {
    const field=key==='avg'?'planned_avg_impact':`planned_${key}`;
    const mean=pool.reduce((a,r)=>a+r[field],0)/(pool.length||1);
    const sd=Math.sqrt(pool.reduce((a,r)=>a+(r[field]-mean)**2,0)/(pool.length||1));
    z[key]={field,mean,sd};
  }
  const total=CATEGORIES.reduce((a,k)=>a+Math.max(0,Number(weights[k])||0),0);
  for(const r of plans) {
    r.priority_score=pool.includes(r) && total>0 ? CATEGORIES.reduce((a,k)=> {
      const {field,mean,sd}=z[k];
      return a+(sd ? (r[field]-mean)/sd : 0)*Math.max(0,Number(weights[k])||0);
    },0)/total : null;
  }
  // Fixed reference population before search, position or personal-pool filters.
  return plans.sort((a,b)=>(b.priority_score??-Infinity)-(a.priority_score??-Infinity) || a.batter_name.localeCompare(b.batter_name));
}
export function replacementDelta(candidate, incumbent) {
  return Object.fromEntries(['r','hr','rbi','sb','ab','h','avg_impact','pa'].map(key=>[key,
    finite(candidate?.[`planned_${key}`]) && finite(incumbent?.[`planned_${key}`])
      ? candidate[`planned_${key}`]-incumbent[`planned_${key}`] : null]));
}
export function combinedAverage(hits, atBats, player) {
  if (!finite(hits)||!finite(atBats)||atBats<=0||hits<0||hits>atBats||!finite(player?.planned_h)||!finite(player?.planned_ab)) return null;
  return (Number(hits)+player.planned_h)/(Number(atBats)+player.planned_ab);
}
export function hitterSignals(row) {
  const signals=[];
  if (!row.active_mlb) signals.push('inactive');
  if (!row.eligible) signals.push('limited');
  if (row.eligible && row.pa_season < 200) signals.push('short_season');
  if (row.team_games_7>=3 && row.team_games_prev7>=3 &&
      finite(row.pa_per_team_game_7)&&finite(row.pa_per_team_game_prev7)) {
    const change=row.pa_per_team_game_7-row.pa_per_team_game_prev7;
    if(change>=.8) signals.push('role_up');
    if(change<=-.8) signals.push('role_down');
  }
  if(row.measured_bbe_14>=20 && row.measured_bbe_prev14>=20 && finite(row.hard_hit_14)&&finite(row.hard_hit_prev14)
      && row.hard_hit_14-row.hard_hit_prev14>=.1 && row.pa_14>=30 && row.pa_prev14>=30
      && row.k_rate_14<=row.k_rate_prev14+.03) signals.push('contact_up');
  if(row.covered_ab_30>=50 && row.coverage_30>=.9 && row.pa_coverage_30>=.95 && row.pa_coverage_30<=1.05
      && finite(row.covered_xba_30)&&finite(row.covered_avg_30)) {
    if(row.covered_xba_30-row.covered_avg_30>=.04) signals.push('under_contact');
    if(row.covered_avg_30-row.covered_xba_30>=.04) signals.push('over_contact');
  }
  if(row.sb_30>=3) signals.push('steal_activity');
  return signals.length?signals:['steady'];
}

export function matchHitterNames(text, rows) {
  const normalize=value=>value.normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/[’‘]/g,"'").trim().toLowerCase().replace(/\s+/g,' ');
  const index=new Map();
  for(const row of rows){const key=normalize(row.batter_name);index.set(key,[...(index.get(key)||[]),row.batter_id]);}
  const matched=new Set(), unresolved=[];
  for(const line of text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)){
    const ids=index.get(normalize(line));
    if(ids?.length===1)matched.add(ids[0]);else unresolved.push(line);
  }
  return {matched:[...matched],unresolved};
}
