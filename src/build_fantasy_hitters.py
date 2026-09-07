"""Official 5x5 totals, tracked-contact evidence and daily hitter planning baselines.

No player-name parsing, inferred RBI/SB, fabricated lineup, or BvP multiplier.
Source windows stop at the committed Statcast cutoff. Roster/schedule freshness
is recorded separately; estimates are planning paces, not calibrated forecasts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from src.common import load_config, project_path
from src.extract_game_context import API_ROOT, fetch_json
from src.build_matchup_stream_planner import normalize_team, schedule_url

COUNTS = {'pa': 'plateAppearances', 'ab': 'atBats', 'h': 'hits', 'r': 'runs',
          'hr': 'homeRuns', 'rbi': 'rbi', 'sb': 'stolenBases', 'cs': 'caughtStealing',
          'bb': 'baseOnBalls', 'k': 'strikeOuts', 'games': 'gamesPlayed'}
SWINGS = {'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
          'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
          'foul_bunt', 'missed_bunt', 'bunt_foul_tip'}
WHIFFS = {'swinging_strike', 'swinging_strike_blocked', 'missed_bunt'}
HITS = {'single', 'double', 'triple', 'home_run'}
NO_AB = {'walk', 'intent_walk', 'hit_by_pitch', 'sac_bunt', 'sac_fly',
         'sac_fly_double_play', 'catcher_interf', 'sac_bunt_double_play'}


def ratio(n, d):
    return float(n) / float(d) if d and pd.notna(d) and pd.notna(n) else None


class SourceCache:
    def __init__(self, path: Path, offline=False):
        self.path, self.offline, self.sources = path, offline, []
        path.mkdir(parents=True, exist_ok=True)

    def get(self, url):
        file = self.path / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        if self.offline:
            saved = json.loads(file.read_text(encoding='utf-8'))
        else:
            saved = {'url': url, 'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
                     'payload': fetch_json(url)}
            tmp = file.with_suffix('.tmp')
            tmp.write_text(json.dumps(saved), encoding='utf-8')
            tmp.replace(file)
        self.sources.append({'url': url, 'fetched_at_utc': saved['fetched_at_utc'],
                             'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
        return saved['payload']


def official_stats(payload):
    """All-player byDateRange includes an aggregate row for traded players.

    Refuse ambiguous duplicates instead of silently double-counting a split.
    """
    blocks = payload.get('stats', [])
    if not blocks:
        raise ValueError('Official hitting statistics are missing')
    block = blocks[0]
    splits = block.get('splits', [])
    if int(block.get('totalSplits', len(splits))) != len(splits):
        raise ValueError('Official hitting response is paginated/incomplete')
    grouped = {}
    for split in splits:
        grouped.setdefault(int(split['player']['id']), []).append(split)
    result = {}
    for player_id, options in grouped.items():
        if len(options) > 1:
            total = [s for s in options if not s.get('team')]
            if len(total) != 1:
                raise ValueError(f'Ambiguous official player split: {player_id}')
            options = total
        s = options[0]
        row = {key: int(s['stat'][value]) for key, value in COUNTS.items()}
        if any(value < 0 for value in row.values()) or row['h'] > row['ab'] or row['ab'] > row['pa']:
            raise ValueError(f'Invalid official hitting counts: {player_id}')
        result[player_id] = {**row, 'batter_id': player_id, 'batter_name': s['player']['fullName'],
                             'position': s.get('position', {}).get('abbreviation', 'Unknown')}
    return result


def stats_url(start, end):
    return f'{API_ROOT}/v1/stats?' + urlencode(dict(stats='byDateRange', group='hitting',
        startDate=str(start), endDate=str(end), season=end.year, sportIds=1, gameType='R',
        playerPool='ALL', limit=20000))


def load_raw(connection, start, end):
    # Include untracked/automatic terminal events omitted by pitch_type filters.
    frame = connection.execute('''
      SELECT game_pk, CAST(game_date AS DATE) game_date, at_bat_number, pitch_number,
        batter batter_id, pitcher pitcher_id, p_throws, stand, events, description,
        CASE WHEN inning_topbot='Top' THEN away_team ELSE home_team END batter_team,
        home_team, away_team, zone, launch_speed, launch_speed_angle,
        estimated_ba_using_speedangle xba, estimated_woba_using_speedangle xwoba
      FROM bronze.raw_statcast
      WHERE game_type='R' AND CAST(game_date AS DATE) BETWEEN ? AND ?
        AND game_pk IS NOT NULL AND batter IS NOT NULL AND at_bat_number IS NOT NULL
      QUALIFY ROW_NUMBER() OVER (PARTITION BY game_pk,at_bat_number,pitch_number
                                ORDER BY loaded_at_utc DESC)=1
    ''', [start, end]).fetchdf()
    frame['game_date'] = pd.to_datetime(frame.game_date)
    frame['batter_team'] = frame.batter_team.map(normalize_team)
    return frame


def terminal_rows(raw):
    return (raw[raw.events.notna() & (raw.events != 'truncated_pa')]
            .sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
            .drop_duplicates(['game_pk', 'at_bat_number'], keep='last').copy())


def contact_metrics(raw):
    pa = terminal_rows(raw)
    result = {}
    for pid, pitches in raw.groupby('batter_id'):
        end = pa[pa.batter_id == pid]
        bbe = end[end.description.isin({'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'})]
        measured = bbe[bbe.launch_speed.notna()]
        classified = bbe[bbe.launch_speed_angle.notna()]
        ab = end[~end.events.isin(NO_AB)]
        # Only compare actual and expected hits on the SAME covered ABs.
        covered = ab[ab.xba.notna() | ab.events.isin({'strikeout', 'strikeout_double_play'})]
        expected_hits = covered.xba.fillna(0).sum()
        covered_hits = covered.events.isin(HITS).sum()
        swings = pitches.description.isin(SWINGS)
        out_zone = pitches.zone.notna() & ~pitches.zone.between(1, 9)
        d = dict(statcast_pa=len(end), bbe=len(bbe), measured_bbe=len(measured),
                 classified_bbe=len(classified), covered_ab=len(covered), statcast_ab=len(ab),
                 coverage=ratio(len(covered), len(ab)),
                 hard_hit=ratio((measured.launch_speed >= 95).sum(), len(measured)),
                 barrel=ratio((classified.launch_speed_angle == 6).sum(), len(classified)),
                 ev=ratio(measured.launch_speed.sum(), len(measured)),
                 whiff=ratio(pitches.description.isin(WHIFFS).sum(), swings.sum()),
                 chase=ratio((swings & out_zone).sum(), out_zone.sum()),
                 covered_avg=ratio(covered_hits, len(covered)),
                 covered_xba=ratio(expected_hits, len(covered)))
        for hand in ('L', 'R'):
            split = bbe[(bbe.p_throws == hand) & bbe.xwoba.notna()]
            d[f'con_{hand}_n'] = len(split)
            d[f'con_{hand}_xwoba'] = ratio(split.xwoba.sum(), len(split))
        result[int(pid)] = d
    return result


def league_rates(stats):
    totals = {key: sum(row[key] for row in stats.values()) for key in COUNTS}
    return {key: ratio(totals[key], totals['ab' if key == 'h' else 'pa']) or 0
            for key in ('r', 'hr', 'rbi', 'sb', 'h', 'ab')}


def pace_rates(season, recent, league):
    """No overlapping prior: season minus last 30d, shrunk by 200 league PA/AB.

    Recent evidence then gets a 100 PA/AB player prior. Constants are explicit
    smoothing heuristics, not claimed stabilization points or fitted parameters.
    """
    rates = {}
    for key in ('r', 'hr', 'rbi', 'sb', 'h', 'ab'):
        denom = 'ab' if key == 'h' else 'pa'
        old_n, old_y = season[denom] - recent[denom], season[key] - recent[key]
        if old_n < 0 or old_y < 0:
            raise ValueError('Official season and recent windows do not reconcile')
        prior = (old_y + 200 * league[key]) / (old_n + 200)
        rates[key] = (recent[key] + 100 * prior) / (recent[denom] + 100)
    return rates


def upcoming_games(payload, now, hands):
    rows, seen = [], set()
    for day in payload.get('dates', []):
        for game in day.get('games', []):
            if game['gamePk'] in seen or game.get('gameType') != 'R':
                continue
            seen.add(game['gamePk'])
            status = game.get('status', {})
            if status.get('abstractGameState') != 'Preview' or status.get('detailedState') in {'Postponed', 'Cancelled', 'Suspended'}:
                continue
            starts = datetime.fromisoformat(game['gameDate'].replace('Z', '+00:00'))
            tbd = status.get('startTimeTBD', False)
            if not tbd and starts <= now:
                continue
            for side, opponent in [('home', 'away'), ('away', 'home')]:
                team = game['teams'][side]['team']
                opp = game['teams'][opponent]
                pitcher = opp.get('probablePitcher', {})
                rows.append(dict(game_pk=game['gamePk'], game_date=game.get('officialDate', day['date']),
                    starts_at_utc=game['gameDate'], time_tbd=tbd, team_id=team['id'],
                    team=normalize_team(team.get('abbreviation')), opponent=normalize_team(opp['team'].get('abbreviation')),
                    home=side == 'home', pitcher_name=pitcher.get('fullName', 'Unannounced'),
                    pitcher_hand=hands.get(pitcher.get('id'), 'Unknown'),
                    venue=game.get('venue', {}).get('name', 'Unknown')))
    return sorted(rows, key=lambda row: (row['game_date'], row['starts_at_utc'], row['team']))


def usage_catalog(raw, cutoff):
    pa = terminal_rows(raw)
    result, defaults = {}, {}
    for days, offset, label in [(14, 0, '14'), (7, 0, '7'), (7, 7, 'prev7')]:
        end = pd.Timestamp(cutoff - timedelta(days=offset))
        start = end - pd.Timedelta(days=days - 1)
        recent = raw[raw.game_date.between(start, end)]
        games = recent[['game_pk', 'home_team', 'away_team']].drop_duplicates('game_pk')
        teams = pd.concat([games[['game_pk','home_team']].rename(columns={'home_team':'team'}),
                           games[['game_pk','away_team']].rename(columns={'away_team':'team'})])
        teams['team'] = teams.team.map(normalize_team)
        team_counts = teams.groupby('team').game_pk.nunique().to_dict()
        for team, count in team_counts.items():
            defaults.setdefault(team, {}).update({f'team_games_{label}': int(count),
                f'pa_per_team_game_{label}': 0.0, f'games_3pa_{label}': 0})
        for (pid, team), p in pa[pa.game_date.between(start, end)].groupby(['batter_id','batter_team']):
            count = team_counts.get(team, 0)
            result.setdefault((int(pid), team), {}).update({f'team_games_{label}': int(count),
                f'pa_per_team_game_{label}': ratio(len(p), count),
                f'games_3pa_{label}': int((p.groupby('game_pk').size() >= 3).sum())})
    return result, defaults


def validate_rates(cache, cutoff):
    """Chronological rate diagnostic conditional on observed next-week PA/AB.

    Does NOT validate future playing time, waiver availability or lineup choices.
    Candidate membership uses only prior PA, never future statistics or rosters.
    """
    errors = {key: [[], []] for key in ('r', 'hr', 'rbi', 'sb', 'h')}
    windows = []
    for offset in (35, 21, 7):
        train_end = cutoff - timedelta(days=offset)
        season = official_stats(cache.get(stats_url(date(cutoff.year, 1, 1), train_end)))
        recent = official_stats(cache.get(stats_url(train_end - timedelta(days=29), train_end)))
        future = official_stats(cache.get(stats_url(train_end + timedelta(days=1), train_end + timedelta(days=7))))
        league = league_rates(season)
        for pid, history in season.items():
            short = recent.get(pid)
            if history['pa'] < 100 or not short or short['pa'] < 30:
                continue
            actual = future.get(pid, {key: 0 for key in COUNTS})
            if not actual['pa']:
                continue
            rates = pace_rates(history, short, league)
            for key in errors:
                denom = 'ab' if key == 'h' else 'pa'
                simple = ratio(history[key], history[denom]) or 0
                errors[key][0].append(abs(rates[key] * actual[denom] - actual[key]))
                errors[key][1].append(abs(simple * actual[denom] - actual[key]))
        windows.append(f'{train_end + timedelta(days=1)}–{train_end + timedelta(days=7)}')
    return [dict(metric=key.upper(), player_weeks=len(values[0]),
                 smoothed_mae=ratio(sum(values[0]), len(values[0])),
                 season_mae=ratio(sum(values[1]), len(values[1])), windows='; '.join(windows),
                 scope='Conditional on observed future PA/AB; not a playing-time or roster backtest')
            for key, values in errors.items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/pipeline_config.json')
    parser.add_argument('--offline', action='store_true', help='Use exact cached API URLs; fail on missing cache')
    parser.add_argument('--evaluate', action='store_true', help='Run three chronological conditional-rate diagnostics')
    args = parser.parse_args()
    config = load_config(args.config)
    out = project_path(config['paths']['outputs_dir']) / 'hitters'
    out.mkdir(parents=True, exist_ok=True)
    cache = SourceCache(out / 'cache', args.offline)
    now = datetime.now(timezone.utc)
    with duckdb.connect(str(project_path(config['paths']['database'])), read_only=True) as con:
        cutoff = con.execute('select max(game_date) from silver.fact_pitch').fetchone()[0]
        raw = load_raw(con, cutoff - timedelta(days=29), cutoff)
        hands = dict(con.execute('select pitcher_id,arg_max(pitcher_throws,game_date) from silver.fact_pitch group by pitcher_id').fetchall())
    starts = max(cutoff + timedelta(days=1), now.astimezone(ZoneInfo('America/New_York')).date())
    specs = {'season': (date(cutoff.year, 1, 1), cutoff),
             '30': (cutoff - timedelta(days=29), cutoff), '14': (cutoff - timedelta(days=13), cutoff),
             '7': (cutoff - timedelta(days=6), cutoff),
             'prev14': (cutoff - timedelta(days=27), cutoff - timedelta(days=14))}
    stats = {key: official_stats(cache.get(stats_url(*dates))) for key, dates in specs.items()}
    teams = cache.get(f'{API_ROOT}/v1/teams?sportId=1')['teams']
    active = {}
    def roster(team):
        return team, cache.get(f'{API_ROOT}/v1/teams/{team["id"]}/roster?rosterType=active')
    with ThreadPoolExecutor(max_workers=4) as pool:
        for team, payload in pool.map(roster, teams):
            if 'roster' not in payload:
                raise ValueError(f'Missing active roster for {team["id"]}')
            for person in payload['roster']:
                active[person['person']['id']] = dict(team_id=team['id'], team=normalize_team(team['abbreviation']),
                    position=person.get('position', {}).get('abbreviation', 'Unknown'))
    games_url = schedule_url(starts, starts + timedelta(days=6))
    games = upcoming_games(cache.get(games_url), now, hands)
    skill = {}
    for label in ('30', '14', 'prev14'):
        start, end = specs[label]
        skill[label] = contact_metrics(raw[raw.game_date.between(pd.Timestamp(start), pd.Timestamp(end))])
    league = league_rates(stats['season'])
    # Precompute team/player usage once per active current team, not on each UI render.
    latest = raw.sort_values('game_date').groupby('batter_id').tail(1).set_index('batter_id')
    rows = []
    usage, usage_defaults = usage_catalog(raw, cutoff)
    for pid, recent in stats['30'].items():
        if pid not in stats['season']:
            raise ValueError(f'Recent player absent from season statistics: {pid}')
        season = stats['season'][pid]
        team = active.get(pid, {}).get('team', latest.loc[pid, 'batter_team'] if pid in latest.index else 'Unknown')
        row = dict(batter_id=pid, batter_name=recent['batter_name'], team=team,
                   schedule_json=json.dumps([g for g in games if g['team'] == team], separators=(',', ':')),
                   position=active.get(pid, {}).get('position', recent['position']),
                   active_mlb=pid in active, data_through=str(cutoff),
                   last_seen=str(latest.loc[pid, 'game_date'].date()) if pid in latest.index else None)
        for label, values in stats.items():
            s = values.get(pid, {key: 0 for key in COUNTS})
            row.update({f'{key}_{label}': s[key] for key in COUNTS})
            row[f'avg_{label}'] = ratio(s['h'], s['ab'])
            row[f'k_rate_{label}'] = ratio(s['k'], s['pa'])
            row[f'bb_rate_{label}'] = ratio(s['bb'], s['pa'])
        for label, values in skill.items():
            row.update({f'{key}_{label}': value for key, value in values.get(pid, {}).items()})
        row.update({f'pace_{key}': value for key, value in pace_rates(season, recent, league).items()})
        row.update({f'season_rate_{key}': ratio(season[key], season['ab' if key == 'h' else 'pa'])
                    for key in ('r','hr','rbi','sb','h','ab')})
        row.update({**{f'{metric}_{label}': 0 for label in ('14','7','prev7')
                      for metric in ('team_games','pa_per_team_game','games_3pa')},
                    **usage_defaults.get(team, {}), **usage.get((pid, team), {})})
        row['pa_coverage_30'] = ratio(row.get('statcast_pa_30', 0), row['pa_30'])
        row['eligible'] = bool(row['active_mlb'] and row['pa_30'] >= 30 and row['pa_season'] >= 100 and
            row['team_games_14'] >= 5 and (row['pa_per_team_game_14'] or 0) >= 2 and
            row['last_seen'] and (cutoff - date.fromisoformat(row['last_seen'])).days <= 4 and
            .95 <= (row['pa_coverage_30'] or 0) <= 1.05)
        rows.append(row)
    evaluation_file = out / 'evaluation.json'
    if args.evaluate:
        source_start = len(cache.sources)
        evaluation = validate_rates(cache, cutoff)
        evaluation_file.write_text(json.dumps(evaluation, indent=2), encoding='utf-8')
        (out / 'evaluation_manifest.json').write_text(json.dumps({
            'data_through': str(cutoff), 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'method': 'conditional-rate-v1', 'sources': cache.sources[source_start:],
            'scope': 'Observed future PA/AB isolate rate quality; no playing-time validation.'
        }, indent=2), encoding='utf-8')
    elif not evaluation_file.exists():
        evaluation_file.write_text('[]', encoding='utf-8')
    # JSON serialization converts absent measurements to null; no fabricated zeros.
    clean_rows = json.loads(pd.DataFrame(rows).to_json(orient='records', double_precision=10))
    (out / 'radar.json').write_text(json.dumps(clean_rows, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (out / 'schedule.json').write_text(json.dumps(games, ensure_ascii=False), encoding='utf-8')
    manifest = dict(data_through=str(cutoff), generated_at_utc=now.isoformat(),
        schedule_fetched_at_utc=next(s['fetched_at_utc'] for s in cache.sources if s['url'] == games_url),
        roster_fetched_at_utc=min(s['fetched_at_utc'] for s in cache.sources if '/roster?' in s['url']),
        schedule_start=str(starts), schedule_end=str(starts + timedelta(days=6)),
        offline=args.offline, sources=sorted(cache.sources, key=lambda s: s['url']),
        rate_method='Default: season count / PA (H uses AB). Optional: recent 30d + 100 PA/AB prior; prior = pre-window season + 200 league PA/AB',
        coverage=dict(players=len(rows), eligible=sum(r['eligible'] for r in rows), active=sum(r['active_mlb'] for r in rows)),
        caveats=['MLB active roster is not confirmed batting lineup or fantasy ownership.',
                 'Current primary position is not platform eligibility.',
                 'Planning pace is not a calibrated forecast; no park, weather, injury or BvP adjustment.',
                 'AVG impact uses expected hits and AB, never an average of player batting averages.',
                 'Statcast covered-AB xBA comparison is descriptive, not a guaranteed rebound.',
                 'Schedule and roster were fetched separately from the completed statistical cutoff.'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest['coverage']), f'; {len(games)} team-game rows; through {cutoff}')


if __name__ == '__main__':
    from src.artifact_lineage import run_versioned
    run_versioned('build_fantasy_hitters', main)
