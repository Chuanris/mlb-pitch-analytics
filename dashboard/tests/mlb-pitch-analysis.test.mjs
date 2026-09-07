import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizePitches, pitchLabAnalysis } from '../src/content/dashboard/pitch-analysis.js';

const rows = [
  {pitcher_id:1,pitcher_name:'A',pitch_name:'Fastball',season:2025,count_state:'0-0',pitch_count:10,
    swing_count:4,whiff_count:1,in_zone_count:6,chase_count:1,batted_ball_count:3,
    measured_batted_ball_count:2,hard_hit_count:1,velocity_total:950,velocity_count:10,
    first_game_date:'2025-04-02',last_game_date:'2025-04-03'},
  {pitcher_id:2,pitcher_name:'B',pitch_name:'Slider',season:2026,count_state:'0-0',pitch_count:20,
    swing_count:10,whiff_count:4,in_zone_count:8,chase_count:2,batted_ball_count:6,
    measured_batted_ball_count:5,hard_hit_count:2,velocity_total:1700,velocity_count:20,
    first_game_date:'2026-03-25',last_game_date:'2026-09-03'},
];
test('single-pass summary preserves totals, measured denominator and date extrema',()=>{
  const result = summarizePitches(rows);
  assert.equal(result.totalPitches,30);
  assert.equal(result.pitchers,2);
  assert.equal(result.whiffs,5);
  assert.equal(result.outOfZone,16);
  assert.equal(result.battedBalls,9);
  assert.equal(result.measuredBattedBalls,7);
  assert.equal(result.firstDate,'2025-04-02');
  assert.equal(result.lastDate,'2026-09-03');
});
test('lab retains measured hard-hit rates and caches unchanged reviewed data',()=>{
  const locations = [];
  const first = pitchLabAnalysis(rows,locations);
  const again = pitchLabAnalysis(rows,locations);
  assert.equal(first.pitchUsageRows,again.pitchUsageRows);
  assert.equal(first.locationRows,again.locationRows);
  assert.equal(first.outcomeRows.find(row=>row.pitch_name==='Fastball').hard_hit_rate,0.5);
  assert.equal(first.pitcherRows.find(row=>row.pitcher_name==='B').hard_hit_rate,0.4);
  assert.equal(first.countRows.reduce((sum,row)=>sum+row.usage_rate,0),1);
  const filtered = pitchLabAnalysis(rows.slice(0,1),locations);
  assert.equal(filtered.pitcherRows.length,1);
  assert.equal(first.pitcherRows.length,2);
});
test('empty data and zero measured contacts remain unknown',()=>{
  assert.equal(summarizePitches([]).firstDate,null);
  const result = pitchLabAnalysis([{...rows[0],measured_batted_ball_count:0,hard_hit_count:0}],[]);
  assert.equal(result.outcomeRows[0].hard_hit_rate,null);
});
