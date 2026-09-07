import unittest
from datetime import date, datetime, timezone
import pandas as pd

from src.build_fantasy_hitters import (COUNTS, official_stats, pace_rates, terminal_rows,
    contact_metrics, upcoming_games, usage_catalog)


def pitch(**kwargs):
    return dict(game_pk=1, game_date=pd.Timestamp('2026-08-30'),at_bat_number=1,pitch_number=1,
        batter_id=10,batter_team='NYY',home_team='NYY',away_team='BOS',p_throws='R',
        events='single',description='hit_into_play',zone=5,launch_speed=100,
        launch_speed_angle=6,xba=.6,xwoba=.8,**kwargs)


class HitterMetricsTests(unittest.TestCase):
    def test_missing_contact_does_not_become_zero_and_coverage_is_explicit(self):
        a=pitch()
        b={**a,'at_bat_number':2,'events':'field_out','launch_speed':None,'launch_speed_angle':None,'xba':None}
        c={**a,'at_bat_number':3,'events':'strikeout','description':'swinging_strike','xba':None,'zone':None}
        d={**a,'at_bat_number':4,'events':'intent_walk','description':'intent_ball','xba':None}
        r=contact_metrics(pd.DataFrame([a,b,c,d]))[10]
        self.assertEqual(r['statcast_pa'],4)
        self.assertEqual(r['measured_bbe'],1)
        self.assertEqual(r['hard_hit'],1)
        self.assertEqual(r['barrel'],1)
        self.assertEqual(r['statcast_ab'],3)
        self.assertEqual(r['covered_ab'],2)
        self.assertAlmostEqual(r['covered_avg'],.5)
        self.assertAlmostEqual(r['covered_xba'],.3)
        self.assertAlmostEqual(r['coverage'],2/3)
        self.assertIsNone(r['chase'])  # Missing zone is not known out-of-zone.

    def test_terminal_pa_count_is_not_pitch_count(self):
        a=pitch()
        b={**a,'pitch_number':2,'events':'double'}
        c={**a,'at_bat_number':2,'events':'truncated_pa'}
        self.assertEqual(terminal_rows(pd.DataFrame([a,b,c])).events.tolist(),['double'])

    def test_season_prior_does_not_double_count_recent_data(self):
        season={k:0 for k in COUNTS};season.update(pa=200,ab=160,h=40,hr=10,r=30,rbi=20,sb=4)
        recent={k:0 for k in COUNTS};recent.update(pa=100,ab=80,h=20,hr=10,r=10,rbi=10,sb=4)
        league={k:.1 for k in ('r','hr','rbi','sb','h','ab')}
        rates=pace_rates(season,recent,league)
        self.assertAlmostEqual(rates['hr'],(10+100*(0+200*.1)/(100+200))/(100+100))
        with self.assertRaises(ValueError):pace_rates(season,{**recent,'hr':11},league)

    def test_stats_refuse_truncation_and_ambiguous_trade_splits(self):
        stat={v:0 for v in COUNTS.values()};stat.update(plateAppearances=10,atBats=8,hits=2)
        split={'stat':stat,'player':{'id':10,'fullName':'Test'},'team':{'id':1}}
        payload={'stats':[{'totalSplits':1,'splits':[split]}]}
        self.assertEqual(official_stats(payload)[10]['h'],2)
        with self.assertRaises(ValueError):official_stats({'stats':[{'totalSplits':2,'splits':[split]}]})
        with self.assertRaises(ValueError):official_stats({'stats':[{'splits':[split,split]}]})
        total={k:v for k,v in split.items() if k!='team'}
        self.assertEqual(official_stats({'stats':[{'splits':[split,total]}]})[10]['pa'],10)

    def test_scheduled_games_deduplicate_and_exclude_started_or_postponed(self):
        team=lambda i,code:{'team':{'id':i,'abbreviation':code}}
        base={'gamePk':1,'gameType':'R','gameDate':'2026-09-07T18:00:00Z','officialDate':'2026-09-07',
              'status':{'abstractGameState':'Preview'},'teams':{'home':team(1,'NYY'),'away':team(2,'BOS')}}
        games=[base,base,{**base,'gamePk':2,'status':{'abstractGameState':'Live'}},
               {**base,'gamePk':3,'status':{'abstractGameState':'Preview','detailedState':'Postponed'}},
               {**base,'gamePk':4,'gameDate':'2026-09-07T10:00:00Z'}]
        rows=upcoming_games({'dates':[{'date':'2026-09-07','games':games}]},datetime(2026,9,7,12,tzinfo=timezone.utc),{})
        self.assertEqual(len(rows),2)
        self.assertEqual({r['team'] for r in rows},{'NYY','BOS'})
        self.assertTrue(all(r['pitcher_hand']=='Unknown' for r in rows))

    def test_bench_days_are_in_opportunity_denominator(self):
        a=pitch()
        b={**a,'game_pk':2,'game_date':pd.Timestamp('2026-08-31'),'batter_id':20}
        usage,defaults=usage_catalog(pd.DataFrame([a,b]),date(2026,8,31))
        self.assertEqual(usage[(10,'NYY')]['pa_per_team_game_14'],.5)
        self.assertEqual(defaults['NYY']['team_games_14'],2)


if __name__=='__main__':unittest.main()
