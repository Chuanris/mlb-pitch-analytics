# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Shared React Data App selected for a source-backed, self-contained dashboard inside this repository.

## Users

- Baseball data analysts exploring pitch strategy and plate-discipline outcomes.
- Fantasy baseball managers comparing recent pitcher skills and workload signals.
- Portfolio reviewers evaluating whether the author can explain and operate the underlying data pipeline.

## Product Purpose

Turn pitch-level MLB Statcast data into an interactive analytical workspace for comparing pitch mix, location, outcomes, model quality, and recent fantasy-relevant pitcher skills. Success means a reader can investigate a question, see the correct denominator, and trace every displayed metric back to reviewed pipeline output.

## Positioning

The dashboard sits directly on a reproducible Bronze/Silver/Gold pipeline whose pitch-level flags and rate denominators are defined once in SQL and reused across the notebook, Excel, and dashboard outputs.

## Operating Context

- The local analytical database covers the complete 2025 regular season and the 2026 regular season through the latest complete available day.
- A Windows Scheduled Task refreshes Statcast data, DuckDB models, reviewed dashboard aggregates, and the self-contained dashboard every day at 06:30 local time.
- Users inspect results locally; publication remains a separate explicit decision.

## Capabilities and Constraints

- Descriptive analysis plus post-release pitch-quality prediction; it does not predict game winners, make pre-pitch claims, or establish causality.
- The Fantasy Pitching Radar is a skills-based 0-100 comparison, not projected fantasy points or an add/drop command.
- Fantasy profiles combine expected whiff, expected hard-hit suppression, K-BB%, chase, and walk suppression over 7-, 14-, or 30-day windows.
- The opening decision board should translate the selected profile into distinct research tasks while preserving the evidence behind every pitcher surfaced.
- Evidence-volume labels describe how far a pitcher clears all four workload gates; they must not be presented as statistical confidence.
- Expected-versus-observed skill gaps are hypothesis flags, not guaranteed positive regression.
- The Upcoming Stream Planner combines confirmed probable starters with recent pitcher skill, opponent batting tendencies, park context, and a separate forecast-risk flag.
- Missing probable starters must remain TBD and unscored; the product may never infer a rotation assignment from historical appearances.
- Stream Score is a research prioritization measure, not projected fantasy points or a start/sit guarantee.
- League Strategy Lab preserves Stream Score and layers a transparent Personalized Fit for league format, pitching priority, and risk tolerance; a Points selection must remain labeled as a skill proxy until full league scoring and workload outcomes are modeled.
- Player Pool Manager lets the user persist browser-local Available, My roster, Watchlist, and Unavailable labels keyed by MLB pitcher ID; labels may filter the decision workspace but must never be presented as live fantasy-platform availability.
- The authored interface supports persistent English and Traditional Chinese modes. Internal filter values stay in canonical English so language changes cannot alter calculations, sorting, or saved player-pool labels; proper names and source-schema fields remain canonical.
- Task-based tabs separate Fantasy decisions, holdout-model review, and pitch-level exploration. Pitch filters appear only in Pitch Lab because they do not scope the Fantasy or model-evaluation queries.
- Fantasy output must show workload minimums and may not imply knowledge of roster availability, probable starts, opponent schedules, wins, saves, earned runs, or official innings pitched.
- The pitch grain is one row per `game_pk + at_bat_number + pitch_number`.
- Whiff rate uses swings, chase rate uses out-of-zone pitches, and hard-hit rate uses batted-ball events.
- Filters must remain truthful for season, pitcher, team, batter side, count state, and pitch family.
- The dashboard must preserve reviewed provenance while the daily refresh advances 2026 coverage.
- The whiff model must keep a strict chronological holdout and exclude same-pitch outcome and future-information fields.
- The hard-hit model must use batted balls as its denominator and exclude launch speed, launch angle, bat speed, and other contact outcomes from predictors.
- Player rolling form must be snapshotted before each player-game and may use only eligible events from earlier games.
- Pitch-type and pitcher-batter matchup history must remain target-specific, pregame-only candidates and earn inclusion on chronological validation.
- Probability calibration must be fitted and accepted on validation only; untouched test results are reporting evidence, not a tuning input.
- Time/weather features must earn inclusion through an out-of-time ablation; source availability alone is not evidence of predictive value.

## Evidence on Hand

- `database/mlb_pitch_analytics.duckdb`: validated analytical database.
- `data/tableau/tableau_pitch_detail.csv`: reviewed 2025-2026 pitch-level export.
- `data/tableau/pitcher_pitch_type_summary.csv`: reviewed pitcher and pitch-type aggregates.
- `outputs/data_quality_report.csv`: deterministic quality checks, including player, recent-form, pitch-type, and matchup window leakage gates.
- `sql/01_build_silver.sql` and `sql/02_build_gold.sql`: metric and aggregation definitions.
- `outputs/models/whiff_model_metrics.json`: out-of-time model metrics and feature contract.
- `outputs/models/whiff_probability_calibrator.joblib`: accepted validation-fitted whiff probability calibration layer.
- `outputs/models/hard_hit_model_metrics.json`: out-of-time hard-hit metrics plus rolling-form and weather ablations.
- `outputs/predictions/whiff_test_predictions.parquet` and `hard_hit_test_predictions.parquet`: complete champion-model holdout scores at the eligible event grain.
- `outputs/predictions/model_leaderboards.csv`: sample-gated pitcher and pitch-type model expectations with observed-rate comparisons.
- `outputs/fantasy/pitcher_fantasy_radar.csv`: sample-gated recent pitcher rankings for three fantasy skill profiles.
- `outputs/fantasy/fantasy_radar_manifest.json`: profile weights, window thresholds, lineage, and explicit decision-support limitations.
- `outputs/fantasy/matchup_stream_planner.csv`: upcoming game-level pitcher research queue with opponent, park, and weather context.
- `outputs/fantasy/matchup_stream_planner_manifest.json`: live schedule and forecast sources, scoring contract, coverage, and limitations.
- `silver.fact_game_context`: one reviewed game-time, venue, roof, and recorded-weather row per `game_pk`.

No testimonials or external performance benchmarks are available and none should be fabricated.

## Product Principles

- Keep every metric traceable to reviewed data and an explicit denominator.
- Make comparisons filter-safe and sample size visible.
- Favor fast investigation over narrative conclusions.
- Keep the displayed coverage period and latest complete day explicit.
- Preserve reproducibility from extraction through presentation.

## Accessibility & Inclusion

Use keyboard-accessible controls, visible focus, readable labels and units, sufficient contrast, and responsive layouts that remain useful on narrow screens.
