import test from 'node:test';
import assert from 'node:assert/strict';
import {planHitter,rankHitters,replacementDelta,combinedAverage,hitterSignals,isFresh,PRIORITIES,matchHitterNames} from '../src/content/dashboard/hitter-analysis.js';

const now=Date.parse('2026-09-07T12:00:00Z');
const dates=['2026-09-07','2026-09-08'];
const games=[{game_pk:1,team:'NYY',game_date:dates[0],starts_at_utc:'2026-09-07T18:00:00Z'},
 {game_pk:2,team:'NYY',game_date:dates[1],starts_at_utc:'2026-09-08T18:00:00Z'},
 {game_pk:3,team:'BOS',game_date:dates[1],starts_at_utc:'2026-09-08T18:00:00Z'}];
const batter={batter_id:1,batter_name:'Power',team:'NYY',eligible:true,active_mlb:true,pa_per_team_game_14:4,
 season_rate_r:.15,season_rate_hr:.08,season_rate_rbi:.2,season_rate_sb:.01,season_rate_h:.3,season_rate_ab:.9};

test('only usable dates and unstarted games create marginal PA',()=>{
 assert.equal(planHitter(batter,games,[dates[0]],.26,now).planned_pa,4);
 assert.equal(planHitter(batter,games,[],.26,now).planned_pa,0);
 assert.equal(planHitter(batter,games,dates,.26,Date.parse('2026-09-07T20:00:00Z')).planned_pa,4);
 assert.equal(planHitter({...batter,eligible:false},games,dates,.26,now).planned_pa,null);
});
test('AVG is AB-weighted and replacement compares the same horizon',()=>{
 const candidate=planHitter(batter,games,dates,.26,now);
 assert.ok(Math.abs(candidate.planned_avg_impact-(7.2*.3-.26*7.2))<1e-10);
 const baseline=planHitter({...batter,team:'BOS'},games,dates,.26,now);
 assert.equal(replacementDelta(candidate,baseline).pa,4);
 assert.equal(combinedAverage(10,50,candidate),(10+candidate.planned_h)/(50+candidate.planned_ab));
 assert.equal(combinedAverage('',50,candidate),null);
 assert.equal(combinedAverage(60,50,candidate),null);
});
test('category needs change ranking while missing and zero weights do not create fake scores',()=>{
 const speed={...batter,batter_id:2,batter_name:'Speed',season_rate_hr:0,season_rate_sb:.15};
 assert.equal(rankHitters([batter,speed],games,{dates,now,weights:PRIORITIES.power})[0].batter_name,'Power');
 assert.equal(rankHitters([batter,speed],games,{dates,now,weights:PRIORITIES.speed})[0].batter_name,'Speed');
 assert.equal(rankHitters([batter],games,{dates,now,weights:{}})[0].priority_score,null);
 assert.equal(rankHitters([{...batter,season_rate_sb:null}],games,{dates,now})[0].priority_score,null);
});
test('small samples and missing tracking cannot trigger a rebound narrative',()=>{
 const row={...batter,covered_ab_30:10,coverage_30:1,pa_coverage_30:1,covered_xba_30:.4,covered_avg_30:.2};
 assert.ok(!hitterSignals(row).includes('under_contact'));
 assert.ok(hitterSignals({...row,covered_ab_30:70}).includes('under_contact'));
 assert.ok(!hitterSignals({...row,covered_ab_30:70,covered_xba_30:null}).includes('under_contact'));
});
test('freshness uses source retrieval time, not rebuilt HTML time',()=>{
 assert.equal(isFresh({generated_at_utc:new Date(now).toISOString()},now),false);
 assert.equal(isFresh({schedule_fetched_at_utc:'2026-09-07T10:00:00Z',roster_fetched_at_utc:'2026-09-07T10:00:00Z'},now),true);
 assert.equal(isFresh({schedule_fetched_at_utc:'2026-09-05T10:00:00Z',roster_fetched_at_utc:'2026-09-07T10:00:00Z'},now),false);
});

test('bulk pool import matches exact names, tolerates accents, and refuses ambiguous names',()=>{
 const rows=[{batter_id:1,batter_name:'José Ramírez'},{batter_id:2,batter_name:'Will Smith'},{batter_id:3,batter_name:'Will Smith'}];
 assert.deepEqual(matchHitterNames(' Jose Ramirez \nJosé Ramírez\nWill Smith\nUnknown',rows),
   {matched:[1],unresolved:['Will Smith','Unknown']});
});
test('invalid AVG targets do not silently become a different target',()=>{
 assert.equal(planHitter(batter,games,dates,null,now).planned_avg_impact,null);
 assert.equal(planHitter(batter,games,dates,1.1,now).planned_avg_impact,null);
});
