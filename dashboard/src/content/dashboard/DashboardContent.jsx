import React, { useEffect, useMemo, useState } from "react";

import {
  ChartRenderer,
  compact,
  DataComponent,
  DataTable,
  Dropdown,
  Filters,
  MetricCard,
  SectionHeader,
  SortableItem,
  SortableRegion,
  useDataApp,
} from "../../data-app-public.jsx";

import { summarizePitches, pitchLabAnalysis, EMPTY_PITCH_LAB } from "./pitch-analysis.js";
import PitcherComparison from "./PitcherComparison.jsx";
import HitterWorkspace from "./HitterWorkspace.jsx";

import { mlbTeamLogos } from "../assets/team-logos.js";
import { localizeChart, localizeColumns, translateDashboard } from "./i18n.js";

const pitchUsageChart = {
  type: "rankedList",
  x: "pitch_name",
  y: "pitch_count",
  sortOrder: "descending",
  initialVisibleCount: 8,
};

const outcomeRateChart = {
  type: "bar",
  x: "pitch_name",
  y: "whiff_rate",
  fields: ["whiff_rate", "chase_rate", "hard_hit_rate"],
  showXAxisLabel: false,
  yLabel: "Rate",
};

const countStrategyChart = {
  type: "heatmap",
  x: "pitch_name",
  y: "usage_rate",
  series: "count_state",
  showXAxisLabel: false,
  showYAxisLabel: false,
  rowHeight: 28,
};

const locationDensityChart = {
  type: "heatmap",
  x: "plate_x_bin",
  y: "pitch_count",
  series: "plate_z_bin",
  xLabel: "Horizontal location (ft)",
  showYAxisLabel: false,
  rowHeight: 18,
};

const seasonPitchMixChart = {
  type: "stackedBar100",
  x: "season",
  y: "pitch_count",
  series: "pitch_name",
  showXAxisLabel: false,
  yLabel: "Share of pitches",
  groupOther: true,
  maxCategories: 8,
};

const velocityWhiffChart = {
  type: "scatter",
  x: "avg_velocity",
  y: "whiff_rate",
  series: "pitch_family",
  xLabel: "Average velocity (mph)",
  yLabel: "Whiff rate",
  startAtZero: false,
};

const modelLiftChart = {
  type: "horizontalBar",
  x: "display_label",
  y: "log_loss_reduction_pct",
  series: "target",
  sortOrder: "descending",
  xLabel: "Model",
  yLabel: "Test log-loss reduction vs baseline (%)",
  startAtZero: true,
};

const modelCalibrationChart = {
  type: "line",
  x: "predicted_rate",
  y: "observed_rate",
  series: "series",
  xLabel: "Predicted probability",
  yLabel: "Observed event rate",
  ratio: true,
  startAtZero: true,
};

const modelLeaderboardChart = {
  type: "horizontalBar",
  x: "entity_label",
  y: "model_edge_pp",
  sortOrder: "descending",
  xLabel: "Entity",
  yLabel: "Model edge vs test average (pp)",
  startAtZero: true,
};

const fantasyRadarChart = {
  type: "rankedList",
  x: "pitcher_name",
  y: "fantasy_signal",
  sortOrder: "descending",
  initialVisibleCount: 10,
};

const streamPlannerChart = {
  type: "horizontalBar",
  x: "matchup_label",
  y: "personalized_fit_score",
  sortOrder: "descending",
  xLabel: "Pitcher matchup",
  yLabel: "Personalized fit",
  startAtZero: true,
};

const pitcherColumns = [
  { field: "pitcher_name", label: "Pitcher", presentation: "identity", secondaryField: "pitcher_team" },
  { field: "pitcher_throws", label: "Throws" },
  { field: "pitch_count", label: "Pitches" },
  { field: "avg_velocity", label: "Avg velo" },
  { field: "zone_rate", label: "Zone rate", presentation: "percent" },
  { field: "whiff_rate", label: "Whiff rate", presentation: "percent" },
  { field: "chase_rate", label: "Chase rate", presentation: "percent" },
  { field: "hard_hit_rate", label: "Hard-hit rate", presentation: "percent" },
];

const modelLeaderboardColumns = [
  { field: "rank", label: "Rank" },
  { field: "entity_label", label: "Player / pitch", presentation: "identity", secondaryField: "primary_pitch" },
  { field: "team", label: "Team" },
  { field: "sample_size", label: "Sample" },
  { field: "predicted_rate_display", label: "Expected" },
  { field: "observed_rate_display", label: "Actual" },
  { field: "model_edge_display", label: "Model edge" },
  { field: "actual_minus_expected_display", label: "Actual − expected" },
];

const pitchPredictionColumns = [
  { field: "game_date", label: "Date" },
  { field: "pitcher_name", label: "Pitcher", presentation: "identity", secondaryField: "pitcher_team" },
  { field: "pitch_name", label: "Pitch" },
  { field: "count_state", label: "Count" },
  { field: "release_speed", label: "Velocity" },
  { field: "predicted_probability_display", label: "Probability" },
  { field: "actual_outcome", label: "Observed" },
];

const fantasyRadarColumns = [
  { field: "rank", label: "Overall rank" },
  { field: "pitcher_name", label: "Pitcher", presentation: "identity", secondaryField: "pitcher_team" },
  { field: "research_action_display", label: "Research next" },
  { field: "role_hint_display", label: "Workload" },
  { field: "fantasy_signal_display", label: "Skill signal" },
  { field: "signal_change_display", label: "Previous-window change" },
  { field: "sample_strength_display", label: "Sample strength" },
  { field: "games", label: "Games" },
  { field: "pitches", label: "Pitches" },
  { field: "expected_whiff_display", label: "xWhiff" },
  { field: "expected_hard_hit_display", label: "xHard-hit allowed" },
  { field: "k_minus_bb_display", label: "K-BB" },
  { field: "underlying_skill_gap_display", label: "Underlying gap" },
];

const streamPlannerColumns = [
  { field: "game_time_display", label: "Venue local time" },
  { field: "pitcher_name", label: "Probable pitcher", presentation: "identity", secondaryField: "pitcher_team" },
  { field: "player_pool_status", label: "Player pool" },
  { field: "opponent_team", label: "Opponent" },
  { field: "venue_name", label: "Venue" },
  { field: "personalized_fit_display", label: "Personalized fit" },
  { field: "strategy_action", label: "Scenario action" },
  { field: "stream_score_display", label: "Base stream" },
  { field: "fantasy_signal_display", label: "Pitcher skill" },
  { field: "opponent_matchup_display", label: "Matchup" },
  { field: "weather_risk_display", label: "Weather" },
  { field: "precipitation_display", label: "Rain" },
  { field: "probable_status_display", label: "Starter status" },
];

const streamWeatherRisks = new Set(["Elevated rain risk", "Roof decision", "Weather watch"]);
const playerPoolStorageKey = "mlb-fantasy-player-pool-v1";
const languageStorageKey = "mlb-dashboard-language-v1";
const workspaceStorageKey = "mlb-dashboard-workspace-v1";
const playerPoolStatuses = ["Available", "My roster", "Watchlist", "Unavailable", "Unclassified"];
const workspaces = [
  { id: "fantasy", label: "Fantasy", description: "Streams, player pool, and recent form" },
  { id: "hitters", label: "Hitters", description: "Daily lineup gaps, category needs, and hitter evidence" },
  { id: "compare", label: "Compare", description: "Compare pitchers and next-start strikeout forecasts" },
  { id: "models", label: "Models", description: "Holdout lift, calibration, and scoring" },
  { id: "pitch-lab", label: "Pitch Lab", description: "Usage, pitch shape, counts, and location" },
];
const workspaceSectionIds = {
  hitters: new Set(),
  compare: new Set(),
  fantasy: new Set([
    "dashboard:fantasy-insights",
    "dashboard:fantasy-summary",
    "dashboard:fantasy-radar",
  ]),
  models: new Set([
    "dashboard:model-status",
    "dashboard:model-diagnostics",
    "dashboard:model-leaderboard",
    "dashboard:latest-predictions",
  ]),
  "pitch-lab": new Set([
    "dashboard:metrics",
    "dashboard:pitch-profile",
    "dashboard:arsenal-shape",
    "dashboard:strategy",
    "dashboard:evidence",
  ]),
};

const faviconMarkup = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="#165f4a"/><circle cx="32" cy="32" r="22" fill="#fff9ed"/><path d="M17 19c8 5 10 20 3 27M47 19c-8 5-10 20-3 27" fill="none" stroke="#d9534f" stroke-width="3" stroke-linecap="round"/><path d="m19 24-4 2m6 4-4 2m28-8 4 2m-6 4 4 2" stroke="#d9534f" stroke-width="2" stroke-linecap="round"/></svg>`;
const faviconHref = `data:image/svg+xml,${encodeURIComponent(faviconMarkup)}`;

function WorkspaceIcon({ workspace }) {
  if (workspace === "fantasy") {
    return <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.25" />
      <path d="M6.8 6.7c3 2.3 3.8 7.8 1.2 10.7M17.2 6.7c-3 2.3-3.8 7.8-1.2 10.7M7.6 9l-2 .9m2.8 2.2-2.1.9m10.1-4 2 .9m-2.8 2.2 2.1.9" />
    </svg>;
  }
  if (workspace === "models") {
    return <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 18.5V5.5M4 18.5h16M7 15l3.3-3.5 3 2 4.7-6" />
      <circle cx="7" cy="15" r="1" /><circle cx="10.3" cy="11.5" r="1" /><circle cx="13.3" cy="13.5" r="1" /><circle cx="18" cy="7.5" r="1" />
    </svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="m12 3 8.5 8.5L12 20 3.5 11.5 12 3Z" />
    <path d="M12 3v17M3.5 11.5h17" />
    <circle cx="12" cy="11.5" r="2.2" />
  </svg>;
}

function LocalizedDropdown({ language, label, value, choices, onChange }) {
  const localizedChoices = choices.map((choice) => translateDashboard(language, choice));
  return <Dropdown label={translateDashboard(language, label)} value={translateDashboard(language, value)}
    choices={localizedChoices} onChange={(nextValue) => {
      const selectedIndex = localizedChoices.indexOf(nextValue);
      onChange(choices[selectedIndex] ?? nextValue);
    }} />;
}

function streamSlotKey(row) {
  return `${row.game_pk}:${row.pitcher_team}`;
}

function localizedGameTime(row, language) {
  if (language !== "zh-TW" || !row.game_datetime_local) return row.game_time_label;
  const gameTime = new Date(row.game_datetime_local);
  if (Number.isNaN(gameTime.getTime())) return row.game_time_label;
  return new Intl.DateTimeFormat("zh-TW", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(gameTime);
}

function personalizedStreamFit(row, strikeoutRow, leagueFormat, riskTolerance) {
  if (!hasNumber(row.stream_score)) return { score: null, penalty: 0 };
  const baseScore = Number(row.stream_score);
  const scoringBasis = leagueFormat === "Points skill proxy" && hasNumber(strikeoutRow?.stream_score)
    ? 0.6 * baseScore + 0.4 * Number(strikeoutRow.stream_score)
    : baseScore;
  const weatherPenalty = {
    "Low risk": { "Elevated rain risk": 8, "Roof decision": 4, "Weather watch": 3 },
    "Balanced risk": { "Elevated rain risk": 4, "Roof decision": 2, "Weather watch": 1 },
    "High risk": {},
  }[riskTolerance]?.[row.weather_risk] ?? 0;
  const samplePenalty = {
    "Low risk": { "Qualified sample": 4, "Solid sample": 2 },
    "Balanced risk": { "Qualified sample": 2, "Solid sample": 1 },
    "High risk": {},
  }[riskTolerance]?.[row.fantasy_sample_strength] ?? 0;
  const trendPenalty = row.fantasy_trend === "Cooling"
    ? ({ "Low risk": 3, "Balanced risk": 1, "High risk": 0 }[riskTolerance] ?? 0)
    : 0;
  const penalty = weatherPenalty + samplePenalty + trendPenalty;
  return { score: Math.max(0, Math.min(100, scoringBasis - penalty)), penalty };
}

function safeRate(numerator, denominator) {
  return denominator > 0 ? numerator / denominator : null;
}

function formatRate(value) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value)
    : "—";
}

function formatDecimal(value, digits = 4) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

function hasNumber(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

export function DashboardContent() {
  const {
    snapshot,
    queries,
    filters,
    setFilter,
    reviewedRows,
    chartOverrides,
    visible,
    chartProps,
  } = useDataApp();
  const [language, setLanguage] = useState(() => {
    if (typeof window === "undefined") return "en";
    try {
      return window.localStorage.getItem(languageStorageKey) === "zh-TW" ? "zh-TW" : "en";
    } catch {
      return "en";
    }
  });
  const [activeWorkspace, setActiveWorkspace] = useState(() => {
    if (typeof window === "undefined") return "fantasy";
    try {
      const savedWorkspace = window.localStorage.getItem(workspaceStorageKey);
      return workspaces.some(({ id }) => id === savedWorkspace) ? savedWorkspace : "fantasy";
    } catch {
      return "fantasy";
    }
  });
  const [minimumPitches, setMinimumPitches] = useState("20");
  const [predictionTarget, setPredictionTarget] = useState("Whiff");
  const [leaderboardEntity, setLeaderboardEntity] = useState("Pitcher");
  const [fantasyWindow, setFantasyWindow] = useState("Last 14 days");
  const [fantasyProfile, setFantasyProfile] = useState("Roto balance");
  const [fantasyRole, setFantasyRole] = useState("All workloads");
  const [streamHorizon, setStreamHorizon] = useState("Next 3 days");
  const [streamProfile, setStreamProfile] = useState("Roto balance");
  const [leagueFormat, setLeagueFormat] = useState("Categories");
  const [riskTolerance, setRiskTolerance] = useState("Balanced risk");
  const [streamView, setStreamView] = useState("Scored probables");
  const [playerPoolFilter, setPlayerPoolFilter] = useState("All players");
  const [poolCandidate, setPoolCandidate] = useState("");
  const [poolDraftStatus, setPoolDraftStatus] = useState("Available");
  const [playerPool, setPlayerPool] = useState(() => {
    if (typeof window === "undefined") return {};
    try {
      const stored = JSON.parse(window.localStorage.getItem(playerPoolStorageKey) || "{}");
      return stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
    } catch {
      return {};
    }
  });
  const sourceRows = useMemo(() => reviewedRows("pitch_summary"), [reviewedRows]);
  const locationSourceRows = useMemo(() => reviewedRows("location_density"), [reviewedRows]);
  const modelSourceRows = useMemo(() => reviewedRows("model_evaluation"), [reviewedRows]);
  const calibrationSourceRows = useMemo(() => reviewedRows("model_calibration"), [reviewedRows]);
  const leaderboardSourceRows = useMemo(() => reviewedRows("model_leaderboard"), [reviewedRows]);
  const predictionSourceRows = useMemo(() => reviewedRows("pitch_model_predictions"), [reviewedRows]);
  const fantasySourceRows = useMemo(() => reviewedRows("fantasy_pitcher_radar"), [reviewedRows]);
  const streamSourceRows = useMemo(() => reviewedRows("matchup_stream_planner"), [reviewedRows]);
  const t = (value) => translateDashboard(language, value);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(languageStorageKey, language);
    } catch {
      // The language remains active for this session when browser storage is unavailable.
    }
  }, [language]);

  useEffect(() => {
    try {
      window.localStorage.setItem(workspaceStorageKey, activeWorkspace);
    } catch {
      // The selected workspace remains active for this session when browser storage is unavailable.
    }
  }, [activeWorkspace]);

  useEffect(() => {
    const existingIcon = document.querySelector('link[rel~="icon"]');
    const icon = existingIcon || document.createElement("link");
    const previousHref = icon.getAttribute("href");
    const previousType = icon.getAttribute("type");
    if (!existingIcon) {
      icon.setAttribute("rel", "icon");
      document.head.appendChild(icon);
    }
    icon.setAttribute("type", "image/svg+xml");
    icon.setAttribute("href", faviconHref);
    return () => {
      if (!existingIcon) icon.remove();
      else {
        if (previousHref) icon.setAttribute("href", previousHref);
        else icon.removeAttribute("href");
        if (previousType) icon.setAttribute("type", previousType);
        else icon.removeAttribute("type");
      }
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(playerPoolStorageKey, JSON.stringify(playerPool));
    } catch {
      // Local labels remain usable for this session when browser storage is unavailable.
    }
  }, [playerPool]);

  const pitchSummary = useMemo(() => summarizePitches(sourceRows), [sourceRows]);
  const lab = useMemo(() => activeWorkspace === "pitch-lab"
    ? pitchLabAnalysis(sourceRows, locationSourceRows) : EMPTY_PITCH_LAB,
    [activeWorkspace, sourceRows, locationSourceRows]);
  const analysis = useMemo(() => ({
    ...pitchSummary, ...lab,
    pitcherRows: lab.pitcherRows.filter(row => row.pitch_count >= Number(minimumPitches)),
    dateRange: pitchSummary.firstDate && pitchSummary.lastDate
      ? `${pitchSummary.firstDate} – ${pitchSummary.lastDate}` : t("No reviewed dates"),
  }), [pitchSummary, lab, minimumPitches, language]);

  const modelAnalysis = useMemo(() => {
    const whiffChampion = modelSourceRows.find((row) => row.target_key === "whiff" && row.is_champion);
    const whiffRawChampion = modelSourceRows.find((row) => row.target_key === "whiff" && row.is_champion_base);
    const hardHitChampion = modelSourceRows.find((row) => row.target_key === "hard_hit" && row.is_champion);
    return {
      whiffChampion,
      whiffRawChampion,
      hardHitChampion,
      testRange: whiffChampion?.test_start && whiffChampion?.test_end
        ? `${whiffChampion.test_start} – ${whiffChampion.test_end}` : "the reviewed test window",
      liftRows: modelSourceRows.filter((row) => row.is_shortlist).map((row) => ({
        ...row,
        display_label: t(row.display_label),
        target: t(row.target),
        log_loss_reduction_pct: Number(Number(row.log_loss_reduction_pct).toFixed(2)),
      })),
    };
  }, [modelSourceRows, language]);

  const predictionAnalysis = useMemo(() => {
    const targetKey = predictionTarget === "Whiff" ? "whiff" : "hard_hit";
    const leaderboardRows = leaderboardSourceRows
      .filter((row) => row.target_key === targetKey && row.entity_type === leaderboardEntity)
      .sort((left, right) => Number(left.rank) - Number(right.rank))
      .map((row) => ({
        ...row,
        predicted_rate_display: formatRate(Number(row.predicted_rate)),
        observed_rate_display: formatRate(Number(row.observed_rate)),
        model_edge_display: `${Number(row.model_edge_pp) >= 0 ? "+" : ""}${Number(row.model_edge_pp).toFixed(1)} pp`,
        actual_minus_expected_display: `${Number(row.actual_minus_expected_pp) >= 0 ? "+" : ""}${Number(row.actual_minus_expected_pp).toFixed(1)} pp`,
      }));
    const latestRows = predictionSourceRows
      .filter((row) => row.target_key === targetKey)
      .sort((left, right) => String(right.game_date).localeCompare(String(left.game_date)));
    const firstDates = leaderboardRows.map((row) => row.first_game_date).filter(Boolean).sort();
    const lastDates = leaderboardRows.map((row) => row.last_game_date).filter(Boolean).sort();
    return {
      targetKey,
      targetLabel: targetKey === "whiff" ? "Whiff probability" : "Hard-hit probability allowed",
      denominator: targetKey === "whiff" ? "swings" : "batted-ball events",
      leaderboardRows,
      chartRows: leaderboardRows.slice(0, 8),
      latestRows,
      dateRange: firstDates.length && lastDates.length
        ? `${firstDates[0]} – ${lastDates.at(-1)}` : t("No reviewed dates"),
    };
  }, [leaderboardSourceRows, predictionSourceRows, predictionTarget, leaderboardEntity, language]);

  const streamAnalysis = useMemo(() => {
    const profileKey = {
      "Roto balance": "roto_balance",
      "Strikeout upside": "strikeout_upside",
      "Ratio protection": "ratio_protection",
    }[streamProfile];
    const profilesBySlot = new Map();
    streamSourceRows.forEach((row) => {
      const key = streamSlotKey(row);
      if (!profilesBySlot.has(key)) profilesBySlot.set(key, new Map());
      profilesBySlot.get(key).set(row.profile_key, row);
    });
    const personalize = (row) => {
      const strikeoutRow = profilesBySlot.get(streamSlotKey(row))?.get("strikeout_upside");
      const fit = personalizedStreamFit(row, strikeoutRow, leagueFormat, riskTolerance);
      const strategyAction = !hasNumber(fit.score)
        ? "Wait for evidence"
        : fit.score >= 80
          ? "Priority shortlist"
          : fit.score >= 70
            ? "Shortlist"
            : "Below threshold";
      return {
        ...row,
        player_pool_status_key: playerPool[String(row.pitcher_id)] || "Unclassified",
        player_pool_status: t(playerPool[String(row.pitcher_id)] || "Unclassified"),
        personalized_fit_score: hasNumber(fit.score) ? Number(fit.score.toFixed(1)) : null,
        personalized_fit_display: hasNumber(fit.score) ? Number(fit.score).toFixed(1) : t("Not scored"),
        strategy_action: t(strategyAction),
        scenario_penalty: fit.penalty,
        game_time_display: localizedGameTime(row, language),
        stream_score_display: hasNumber(row.stream_score) ? Number(row.stream_score).toFixed(1) : t("Not scored"),
        fantasy_signal_display: hasNumber(row.fantasy_signal) ? Number(row.fantasy_signal).toFixed(1) : t("Not qualified"),
        opponent_matchup_display: hasNumber(row.opponent_matchup_signal) ? Number(row.opponent_matchup_signal).toFixed(1) : t("Unavailable value"),
        precipitation_display: hasNumber(row.precipitation_probability)
          ? `${Math.round(Number(row.precipitation_probability))}%`
          : t("Unavailable value"),
        weather_risk_display: t(row.weather_risk),
        probable_status_display: t(row.probable_status),
        matchup_label: language === "zh-TW"
          ? `${row.pitcher_name} 對 ${row.opponent_team} · ${String(row.game_date).slice(5)}`
          : `${row.pitcher_name} vs ${row.opponent_team} · ${String(row.game_date).slice(5)}`,
      };
    };
    const profileRows = streamSourceRows.filter((row) => row.profile_key === profileKey);
    const availableDates = [...new Set(profileRows.map((row) => row.game_date).filter(Boolean))].sort();
    const horizonDays = streamHorizon === "Next 3 days" ? 3 : 7;
    const includedDates = new Set(availableDates.slice(0, horizonDays));
    const allHorizonRows = profileRows.filter((row) => includedDates.has(row.game_date));
    const horizonRows = playerPoolFilter === "All players"
      ? allHorizonRows
      : allHorizonRows.filter((row) => (playerPool[String(row.pitcher_id)] || "Unclassified") === playerPoolFilter);
    const filteredSourceRows = streamView === "All scheduled slots"
      ? horizonRows
      : streamView === "Weather watch"
        ? horizonRows.filter((row) => streamWeatherRisks.has(row.weather_risk))
        : horizonRows.filter((row) => row.probable_status === "Confirmed probable" && hasNumber(row.stream_score));
    const displayRows = filteredSourceRows
      .map(personalize)
      .sort((left, right) => {
        const scoreOrder = (Number(right.personalized_fit_score) || -1) - (Number(left.personalized_fit_score) || -1);
        return scoreOrder || String(left.game_datetime_utc).localeCompare(String(right.game_datetime_utc));
      });
    const chartRows = displayRows.filter((row) => hasNumber(row.personalized_fit_score)).slice(0, 10);
    const chartKeys = new Set(chartRows.map(streamSlotKey));
    const chartSourceRows = filteredSourceRows.filter((row) => chartKeys.has(streamSlotKey(row)));
    const confirmedRows = horizonRows.filter((row) => row.probable_status === "Confirmed probable");
    const scoredRows = confirmedRows.filter((row) => hasNumber(row.stream_score));
    const personalizedScoredRows = scoredRows.map(personalize);
    const shortlistKeys = new Set(personalizedScoredRows
      .filter((row) => Number(row.personalized_fit_score) >= 70)
      .map(streamSlotKey));
    const weatherRows = confirmedRows.filter((row) => streamWeatherRisks.has(row.weather_risk));
    const poolSourceRows = allHorizonRows.filter((row) => row.probable_status === "Confirmed probable" && hasNumber(row.stream_score));
    const candidateMap = new Map();
    poolSourceRows.forEach((row) => {
      const key = String(row.pitcher_id);
      if (!candidateMap.has(key)) candidateMap.set(key, row);
    });
    const poolCandidates = [...candidateMap.values()]
      .map((row) => ({
        ...personalize(row),
        candidate_label: `${row.pitcher_name} · ${row.pitcher_team}`,
      }))
      .sort((left, right) => Number(right.personalized_fit_score) - Number(left.personalized_fit_score));
    const classifiedRows = poolCandidates.filter((row) => row.player_pool_status_key !== "Unclassified");
    return {
      displayRows,
      sourceRows: filteredSourceRows,
      chartSourceRows,
      chartRows,
      confirmedRows,
      scoredRows,
      shortlistRows: personalizedScoredRows.filter((row) => Number(row.personalized_fit_score) >= 70),
      shortlistSourceRows: scoredRows.filter((row) => shortlistKeys.has(streamSlotKey(row))),
      weatherRows,
      poolSourceRows,
      poolCandidates,
      classifiedRows,
      tbdCount: horizonRows.filter((row) => row.probable_status === "TBD").length,
      dateRange: availableDates.length
        ? `${availableDates[0]} – ${availableDates[Math.min(horizonDays, availableDates.length) - 1]}`
        : t("No upcoming games"),
    };
  }, [streamSourceRows, streamHorizon, streamProfile, leagueFormat, riskTolerance, streamView, playerPoolFilter, playerPool, language]);

  const effectivePoolCandidate = streamAnalysis.poolCandidates.some((row) => row.candidate_label === poolCandidate)
    ? poolCandidate
    : streamAnalysis.poolCandidates[0]?.candidate_label || "No scored probable pitchers";

  const savePlayerPoolStatus = () => {
    const candidate = streamAnalysis.poolCandidates.find((row) => row.candidate_label === effectivePoolCandidate);
    if (!candidate) return;
    setPlayerPool((current) => {
      const next = { ...current };
      if (poolDraftStatus === "Unclassified") delete next[String(candidate.pitcher_id)];
      else next[String(candidate.pitcher_id)] = poolDraftStatus;
      return next;
    });
  };

  const removePlayerPoolStatus = (pitcherId) => {
    setPlayerPool((current) => {
      const next = { ...current };
      delete next[String(pitcherId)];
      return next;
    });
  };

  const setPlayerPoolStatus = (pitcherId, status) => {
    setPlayerPool((current) => ({ ...current, [String(pitcherId)]: status }));
  };

  const fantasyAnalysis = useMemo(() => {
    const profileRows = fantasySourceRows
      .filter((row) => row.window_label === fantasyWindow && row.profile === fantasyProfile)
      .sort((left, right) => Number(left.rank) - Number(right.rank));
    const roleRows = fantasyRole === "All workloads"
      ? profileRows
      : profileRows.filter((row) => row.role_hint === fantasyRole);
    const displayRows = roleRows.map((row) => ({
      ...row,
      research_action_display: t(row.research_action),
      role_hint_display: t(row.role_hint),
      sample_strength_display: t(row.sample_strength),
      fantasy_signal_display: Number(row.fantasy_signal).toFixed(1),
      signal_change_display: row.signal_change !== null && row.signal_change !== undefined && Number.isFinite(Number(row.signal_change))
        ? `${Number(row.signal_change) >= 0 ? "+" : ""}${Number(row.signal_change).toFixed(1)}`
        : t("Newly qualified"),
      expected_whiff_display: formatRate(Number(row.expected_whiff_rate)),
      expected_hard_hit_display: formatRate(Number(row.expected_hard_hit_rate)),
      k_minus_bb_display: formatRate(Number(row.k_minus_bb_rate)),
      underlying_skill_gap_display: `${Number(row.underlying_skill_gap_pp) >= 0 ? "+" : ""}${Number(row.underlying_skill_gap_pp).toFixed(1)} pp`,
    }));
    const topStarter = roleRows.find((row) => row.role_hint === "Starter workload");
    const insightRows = [];
    const usedPitchers = new Set();
    const addInsight = (insightType, row, rationale) => {
      if (!row || usedPitchers.has(row.pitcher_id)) return;
      usedPitchers.add(row.pitcher_id);
      insightRows.push({ ...row, insightType, rationale });
    };
    addInsight(
      "Skill leader",
      roleRows[0],
      roleRows[0]
        ? language === "zh-TW"
          ? `在${t(fantasyProfile)}策略中整體排名第 ${roleRows[0].rank}，技能訊號為 ${Number(roleRows[0].fantasy_signal).toFixed(1)}。`
          : `No. ${roleRows[0].rank} overall in ${fantasyProfile.toLowerCase()} with a ${Number(roleRows[0].fantasy_signal).toFixed(1)} skill signal.`
        : language === "zh-TW" ? "目前檢視沒有符合條件的投手。" : "No qualified pitcher in this view.",
    );
    const starterCandidate = roleRows.find((row) => row.role_hint === "Starter workload");
    addInsight(
      "Starter stream",
      starterCandidate,
      starterCandidate
        ? language === "zh-TW"
          ? `近期 ${starterCandidate.games} 場、${starterCandidate.pitches} 球，K-BB% 為 ${Number(starterCandidate.k_minus_bb_rate * 100).toFixed(1)}%。`
          : `${starterCandidate.games} recent games, ${starterCandidate.pitches} pitches, and a ${Number(starterCandidate.k_minus_bb_rate * 100).toFixed(1)}% K-BB rate.`
        : language === "zh-TW" ? "目前檢視沒有符合先發工作量的投手。" : "No starter workload qualifies in this view.",
    );
    const momentumCandidate = [...roleRows]
      .filter((row) => Number(row.fantasy_signal) >= 65 && Number.isFinite(Number(row.signal_change)))
      .sort((left, right) => Number(right.signal_change) - Number(left.signal_change))
      .find((row) => !usedPitchers.has(row.pitcher_id));
    addInsight(
      "Momentum watch",
      momentumCandidate,
      momentumCandidate
        ? language === "zh-TW"
          ? `相較前一個等長區間為 ${Number(momentumCandidate.signal_change) >= 0 ? "+" : ""}${Number(momentumCandidate.signal_change).toFixed(1)}；目前趨勢為${t(momentumCandidate.trend_status)}。`
          : `${Number(momentumCandidate.signal_change) >= 0 ? "+" : ""}${Number(momentumCandidate.signal_change).toFixed(1)} versus the previous equal-length window; current status is ${String(momentumCandidate.trend_status).toLowerCase()}.`
        : language === "zh-TW" ? "目前檢視沒有可比較的動能訊號。" : "No comparable momentum signal in this view.",
    );
    const underlyingCandidate = [...roleRows]
      .filter((row) => Number(row.fantasy_signal) >= 60 && Number(row.underlying_skill_gap_pp) > 0)
      .sort((left, right) => Number(right.underlying_skill_gap_pp) - Number(left.underlying_skill_gap_pp))
      .find((row) => !usedPitchers.has(row.pitcher_id));
    addInsight(
      "Underlying upside",
      underlyingCandidate,
      underlyingCandidate
        ? language === "zh-TW"
          ? `在綜合研究指標中，模型預期的揮空與抑制強擊球能力比近期實際比率高 ${Number(underlyingCandidate.underlying_skill_gap_pp).toFixed(1)} 點。`
          : `Model-expected whiff and hard-hit skill is ${Number(underlyingCandidate.underlying_skill_gap_pp).toFixed(1)} points stronger than recent observed rates on the composite research flag.`
        : language === "zh-TW" ? "沒有正向底層能力差距達到目前門檻。" : "No positive underlying gap meets the current threshold.",
    );
    return {
      displayRows,
      chartRows: displayRows.slice(0, 10),
      insightRows,
      topStarter,
      windowEnd: profileRows[0]?.window_end ?? "—",
      qualifiedCount: displayRows.length,
      highSkillCount: displayRows.filter((row) => Number(row.fantasy_signal) >= 80).length,
      risingCount: displayRows.filter((row) => Number(row.fantasy_signal) >= 65 && Number(row.signal_change) >= 5).length,
      starterCount: displayRows.filter((row) => row.role_hint === "Starter workload").length,
    };
  }, [fantasySourceRows, fantasyWindow, fantasyProfile, fantasyRole, language]);

  const metrics = [
    {
      id: "pitch-count",
      title: t("Reviewed pitches"),
      description: t("Distinct reviewed pitch records remaining after the selected filters."),
      value: compact(analysis.totalPitches),
      comparison: language === "zh-TW" ? `${analysis.pitchers} 位投手 · ${analysis.dateRange}` : `${analysis.pitchers} pitchers · ${analysis.dateRange}`,
    },
    {
      id: "zone-rate",
      title: t("Zone rate"),
      description: t("Pitches in Statcast zones 1 through 9 divided by all reviewed pitches."),
      value: formatRate(safeRate(analysis.inZone, analysis.totalPitches)),
      comparison: language === "zh-TW" ? `${compact(analysis.inZone)} 球進入好球帶` : `${compact(analysis.inZone)} pitches in zone`,
    },
    {
      id: "whiff-rate",
      title: t("Whiff rate"),
      description: t("Swinging strikes divided by swings."),
      value: formatRate(safeRate(analysis.whiffs, analysis.swings)),
      comparison: language === "zh-TW" ? `${compact(analysis.whiffs)} 次揮空 / ${compact(analysis.swings)} 次揮棒` : `${compact(analysis.whiffs)} whiffs / ${compact(analysis.swings)} swings`,
    },
    {
      id: "chase-rate",
      title: t("Chase rate"),
      description: t("Out-of-zone swings divided by pitches outside Statcast zones 1 through 9."),
      value: formatRate(safeRate(analysis.chases, analysis.outOfZone)),
      comparison: language === "zh-TW" ? `${compact(analysis.chases)} 次追打 / ${compact(analysis.outOfZone)} 顆壞球` : `${compact(analysis.chases)} chases / ${compact(analysis.outOfZone)} out of zone`,
    },
    {
      id: "hard-hit-rate",
      title: t("Hard-hit rate"),
      description: t("Batted balls at 95 mph or harder divided by reviewed batted-ball events."),
      value: formatRate(safeRate(analysis.hardHits, analysis.measuredBattedBalls)),
      comparison: language === "zh-TW" ? `${compact(analysis.hardHits)} 顆強擊球 / ${compact(analysis.measuredBattedBalls)} 次有效測量（全部 ${compact(analysis.battedBalls)} 次）` : `${compact(analysis.hardHits)} hard hits / ${compact(analysis.measuredBattedBalls)} measured BBE (${compact(analysis.battedBalls)} total)`,
    },
  ];

  const modelMetrics = [
    {
      id: "whiff-model-champion",
      title: t("Whiff champion"),
      description: language === "zh-TW"
        ? `經驗證選出的滾動、球種與對戰 HGB，並使用 Platt calibration；${formatRate(modelAnalysis.whiffChampion?.matchup_history_coverage)} 的揮棒具有對戰歷史。`
        : `Validation-selected rolling, pitch-type, and matchup HGB with Platt calibration. Matchup history is available for ${formatRate(modelAnalysis.whiffChampion?.matchup_history_coverage)} of swings.`,
      value: t("Calibrated HGB"),
      comparison: `Log loss ${formatDecimal(modelAnalysis.whiffChampion?.log_loss)} · AUC ${formatDecimal(modelAnalysis.whiffChampion?.roc_auc)}`,
      sourceRows: modelAnalysis.whiffChampion ? [modelAnalysis.whiffChampion] : [],
    },
    {
      id: "hard-hit-model-champion",
      title: t("Hard-hit champion"),
      description: language === "zh-TW"
        ? `經驗證選出的滾動與球種 HGB。模型排除對戰特徵；${formatRate(modelAnalysis.hardHitChampion?.matchup_history_coverage)} 的擊球事件具有先前對戰歷史。`
        : `Validation-selected rolling and pitch-type HGB. Matchup is excluded; prior matchup history exists for ${formatRate(modelAnalysis.hardHitChampion?.matchup_history_coverage)} of batted balls.`,
      value: t("Pitch-type HGB"),
      comparison: `Log loss ${formatDecimal(modelAnalysis.hardHitChampion?.log_loss)} · AUC ${formatDecimal(modelAnalysis.hardHitChampion?.roc_auc)}`,
      sourceRows: modelAnalysis.hardHitChampion ? [modelAnalysis.hardHitChampion] : [],
    },
    {
      id: "whiff-calibration-status",
      title: t("Whiff calibration"),
      description: t("Platt scaling was accepted only after improving both log loss and expected calibration error on the chronological validation tail."),
      value: t(modelAnalysis.whiffChampion?.probability_calibration_accepted ? "Accepted" : "Not promoted"),
      comparison: `Test ECE ${formatDecimal(modelAnalysis.whiffRawChampion?.expected_calibration_error)} → ${formatDecimal(modelAnalysis.whiffChampion?.expected_calibration_error)}`,
      sourceRows: [modelAnalysis.whiffRawChampion, modelAnalysis.whiffChampion].filter(Boolean),
    },
  ];

  const streamMetrics = [
    {
      id: "stream-confirmed-probables",
      title: t("Confirmed probables"),
      description: t("Upcoming pitcher slots with a probable starter supplied by the MLB schedule response."),
      value: compact(streamAnalysis.confirmedRows.length),
      comparison: language === "zh-TW" ? `${streamAnalysis.tbdCount} 個輪值席位仍待確認` : `${streamAnalysis.tbdCount} rotation slots still TBD`,
      sourceRows: streamAnalysis.confirmedRows,
    },
    {
      id: "stream-scored-matchups",
      title: t("Scored matchups"),
      description: t("Confirmed probables that also meet the current 14-day pitcher-skill evidence thresholds."),
      value: compact(streamAnalysis.scoredRows.length),
      comparison: language === "zh-TW" ? `${t(streamProfile)}需求 · ${streamAnalysis.dateRange}` : `${streamProfile} priority · ${streamAnalysis.dateRange}`,
      sourceRows: streamAnalysis.scoredRows,
    },
    {
      id: "stream-strong-options",
      title: t("Personalized shortlist"),
      description: t("Scored matchups with a Personalized Fit of 70 or higher under the selected league and risk scenario."),
      value: compact(streamAnalysis.shortlistRows.length),
      comparison: `${t(leagueFormat)} · ${t(riskTolerance)}`,
      sourceRows: streamAnalysis.shortlistSourceRows,
    },
    {
      id: "stream-weather-flags",
      title: t("Weather flags"),
      description: t("Confirmed probable matchups with rain or roof-decision forecast risk near scheduled first pitch."),
      value: compact(streamAnalysis.weatherRows.length),
      comparison: t("Base score unchanged; fit may be reduced"),
      sourceRows: streamAnalysis.weatherRows,
    },
  ];

  const fantasyMetrics = [
    {
      id: "fantasy-qualified-pool",
      title: t("Qualified pool"),
      description: t("Pitchers meeting all pitch, batter-faced, scored-swing, and scored-contact minimums for the selected view."),
      value: compact(fantasyAnalysis.qualifiedCount),
      comparison: `${t(fantasyWindow)} · ${t(fantasyRole)}`,
      sourceRows: fantasyAnalysis.displayRows,
    },
    {
      id: "fantasy-high-skill-pool",
      title: t("High-skill options"),
      description: t("Qualified pitchers with a profile-specific skill signal of 80 or higher."),
      value: compact(fantasyAnalysis.highSkillCount),
      comparison: language === "zh-TW" ? `${t(fantasyProfile)}門檻：80` : `${fantasyProfile} threshold: 80`,
      sourceRows: fantasyAnalysis.displayRows.filter((row) => Number(row.fantasy_signal) >= 80),
    },
    {
      id: "fantasy-rising-pool",
      title: t("Rising candidates"),
      description: t("Pitchers scoring at least 65 with a five-point or larger gain versus the previous equal-length window."),
      value: compact(fantasyAnalysis.risingCount),
      comparison: t("Momentum screen"),
      sourceRows: fantasyAnalysis.displayRows.filter((row) => Number(row.fantasy_signal) >= 65 && Number(row.signal_change) >= 5),
    },
    {
      id: "fantasy-starter-pool",
      title: t("Starter options"),
      description: t("Pitchers averaging at least 50 pitches per appearance in the selected window."),
      value: compact(fantasyAnalysis.starterCount),
      comparison: fantasyAnalysis.topStarter
        ? language === "zh-TW" ? `領先者：${fantasyAnalysis.topStarter.pitcher_name}` : `Leader: ${fantasyAnalysis.topStarter.pitcher_name}`
        : t("No qualified starter workload"),
      sourceRows: fantasyAnalysis.displayRows.filter((row) => row.role_hint === "Starter workload"),
    },
  ];

  const usageChart = localizeChart(language, chartOverrides["pitch-usage"] ?? pitchUsageChart);
  const outcomesChart = localizeChart(language, chartOverrides["outcome-rates"] ?? outcomeRateChart);
  const strategyChart = localizeChart(language, chartOverrides["count-strategy"] ?? countStrategyChart);
  const locationChart = localizeChart(language, chartOverrides["location-density"] ?? locationDensityChart);
  const seasonMixChart = localizeChart(language, chartOverrides["pitch-mix-by-season"] ?? seasonPitchMixChart);
  const velocityProfileChart = localizeChart(language, chartOverrides["velocity-whiff-profile"] ?? velocityWhiffChart);
  const liftChart = localizeChart(language, chartOverrides["model-lift"] ?? modelLiftChart);
  const calibrationChart = localizeChart(language, chartOverrides["model-calibration"] ?? modelCalibrationChart);
  const calibrationDisplayRows = calibrationSourceRows.map((row) => ({
    ...row,
    target: t(row.target),
    series: t(row.series),
  }));
  const leaderboardChart = localizeChart(language, chartOverrides["model-leaderboard-chart"] ?? {
    ...modelLeaderboardChart,
    yLabel: predictionAnalysis.targetKey === "whiff"
      ? "Expected whiff edge vs average (pp)"
      : "Expected hard-hit prevention edge vs average (pp)",
  });
  const indexPitchTypeChart = localizeChart(language, {
    type: "bar",
    x: "entity_label",
    y: "predicted_rate",
    fields: ["predicted_rate", "observed_rate"],
    showXAxisLabel: false,
    yLabel: "Expected whiff rate",
    startAtZero: true,
  });
  const indexPitchTypeRows = leaderboardSourceRows
    .filter((row) => row.target_key === "whiff" && row.entity_type === "Pitch type")
    .sort((left, right) => Number(left.rank) - Number(right.rank))
    .slice(0, 8);
  const fantasyChart = localizeChart(language, chartOverrides["fantasy-radar-chart"] ?? fantasyRadarChart);
  const streamChart = localizeChart(language, {
    ...(chartOverrides["stream-planner-chart"] ?? streamPlannerChart),
    y: "personalized_fit_score",
    yLabel: "Personalized fit",
  });
  const localizedPitcherColumns = localizeColumns(language, pitcherColumns);
  const localizedModelLeaderboardColumns = localizeColumns(language, modelLeaderboardColumns);
  const localizedPitchPredictionColumns = localizeColumns(language, pitchPredictionColumns);
  const localizedFantasyRadarColumns = localizeColumns(language, fantasyRadarColumns);
  const localizedStreamPlannerColumns = localizeColumns(language, streamPlannerColumns);
  const localizedFilters = (snapshot.filters ?? []).map((filter) => ({ ...filter, label: t(filter.label) }));
  const dashboardRows = [
    {
      id: "dashboard:stream-summary",
      className: "metric-strip mlb-metric-strip",
      kind: "metrics",
      label: t("Upcoming stream summary"),
      items: streamMetrics.map(({ id }) => id),
      header: <SectionHeader id="dashboard:stream-summary-title" title={t("League Strategy Lab")}
        filters={<div className="mlb-section-controls" role="group" aria-label={t("League strategy controls")}>
          <LocalizedDropdown language={language} label="Horizon" value={streamHorizon} choices={["Next 3 days", "Next 7 days"]}
            onChange={setStreamHorizon} />
          <LocalizedDropdown language={language} label="League format" value={leagueFormat} choices={["Categories", "Points skill proxy"]}
            onChange={setLeagueFormat} />
          <LocalizedDropdown language={language} label="Pitching priority" value={streamProfile} choices={["Roto balance", "Strikeout upside", "Ratio protection"]}
            onChange={setStreamProfile} />
          <LocalizedDropdown language={language} label="Risk tolerance" value={riskTolerance} choices={["Low risk", "Balanced risk", "High risk"]}
            onChange={setRiskTolerance} />
          <LocalizedDropdown language={language} label="Player pool" value={playerPoolFilter} choices={["All players", ...playerPoolStatuses]}
            onChange={setPlayerPoolFilter} />
          <LocalizedDropdown language={language} label="Planner view" value={streamView} choices={["Scored probables", "All scheduled slots", "Weather watch"]}
            onChange={setStreamView} />
        </div>} />,
    },
    {
      id: "dashboard:stream-planner",
      className: "mlb-analysis-grid mlb-analysis-grid--stream",
      label: t("Upcoming stream planner evidence"),
      items: ["stream-player-pool", "stream-planner-chart", "stream-planner-table"],
    },
    {
      id: "dashboard:fantasy-insights",
      className: "dashboard-section-start mlb-fantasy-insight-section",
      label: t("Fantasy decision board"),
      items: ["fantasy-insight-board"],
      header: <SectionHeader id="dashboard:fantasy-insights-title" title={t("Fantasy decision board")}
        filters={<div className="mlb-section-controls" role="group" aria-label={t("Fantasy pitching radar controls")}>
          <LocalizedDropdown language={language} label="Recent window" value={fantasyWindow} choices={["Last 7 days", "Last 14 days", "Last 30 days"]}
            onChange={setFantasyWindow} />
          <LocalizedDropdown language={language} label="Fantasy profile" value={fantasyProfile} choices={["Roto balance", "Strikeout upside", "Ratio protection"]}
            onChange={setFantasyProfile} />
          <LocalizedDropdown language={language} label="Workload" value={fantasyRole} choices={["All workloads", "Starter workload", "Multi-inning workload", "Relief workload"]}
            onChange={setFantasyRole} />
        </div>} />,
    },
    {
      id: "dashboard:fantasy-summary",
      className: "metric-strip mlb-metric-strip",
      kind: "metrics",
      label: t("Fantasy pitching summary"),
      items: fantasyMetrics.map(({ id }) => id),
    },
    {
      id: "dashboard:fantasy-radar",
      className: "mlb-analysis-grid mlb-analysis-grid--fantasy",
      label: t("Fantasy pitching radar evidence"),
      items: ["fantasy-radar-chart", "fantasy-radar-table"],
    },
    { id: "dashboard:metrics", className: "metric-strip mlb-metric-strip dashboard-section-start", kind: "metrics", label: t("Key pitch metrics"), items: metrics.map(({ id }) => id), header: <SectionHeader id="dashboard:metrics-title" title={t("Pitch-level overview")} /> },
    {
      id: "dashboard:model-status",
      className: "metric-strip mlb-metric-strip dashboard-section-start",
      kind: "metrics",
      label: t("Model status"),
      items: modelMetrics.map(({ id }) => id),
      header: <SectionHeader id="dashboard:model-status-title" title={t("Model performance")} />,
    },
    {
      id: "dashboard:model-diagnostics",
      className: "mlb-analysis-grid mlb-analysis-grid--models",
      label: t("Model diagnostics"),
      items: ["model-lift", "model-calibration"],
    },
    {
      id: "dashboard:model-leaderboard",
      className: "mlb-analysis-grid mlb-analysis-grid--leaderboard dashboard-section-start",
      label: t("Model scoring leaderboard"),
      items: ["model-leaderboard-chart", "model-leaderboard-table"],
      header: <SectionHeader id="dashboard:model-leaderboard-title" title={t("Model scoring explorer")}
        filters={<div className="mlb-section-controls" role="group" aria-label={t("Model scoring controls")}>
          <LocalizedDropdown language={language} label="Prediction target" value={predictionTarget} choices={["Whiff", "Hard hit"]}
            onChange={setPredictionTarget} />
          <LocalizedDropdown language={language} label="Leaderboard entity" value={leaderboardEntity} choices={["Pitcher", "Pitch type"]}
            onChange={setLeaderboardEntity} />
        </div>} />,
    },
    {
      id: "dashboard:latest-predictions",
      className: "dashboard-section-start mlb-evidence-section",
      label: t("Latest scored pitches"),
      items: ["latest-pitch-predictions"],
      header: <SectionHeader id="dashboard:latest-predictions-title" title={t("Latest scored pitch detail")} />,
    },
    {
      id: "dashboard:pitch-profile",
      className: "mlb-analysis-grid dashboard-section-start",
      label: t("Pitch profile"),
      items: ["pitch-usage", "outcome-rates"],
      header: <SectionHeader id="dashboard:pitch-profile-title" title={t("Pitch profile")} />,
    },
    {
      id: "dashboard:arsenal-shape",
      className: "mlb-analysis-grid mlb-analysis-grid--arsenal dashboard-section-start",
      label: t("Arsenal shape"),
      items: ["pitch-mix-by-season", "velocity-whiff-profile"],
      header: <SectionHeader id="dashboard:arsenal-shape-title" title={t("Arsenal shape")} />,
    },
    {
      id: "dashboard:strategy",
      className: "mlb-analysis-grid mlb-analysis-grid--strategy dashboard-section-start",
      label: t("Count and location"),
      items: ["count-strategy", "location-density"],
      header: <SectionHeader id="dashboard:strategy-title" title={t("Count and location")} />,
    },
    {
      id: "dashboard:evidence",
      className: "dashboard-section-start mlb-evidence-section",
      label: t("Pitcher comparison"),
      items: ["pitcher-table"],
      header: <SectionHeader id="dashboard:pitcher-comparison-title" title={t("Pitcher comparison")}
        filters={<div className="minimum-pitches" role="group" aria-label={t("Pitcher sample threshold")}>
          <span>{t("Minimum pitches")}</span>
          <LocalizedDropdown language={language} label="Minimum pitches" value={minimumPitches} choices={["10", "20", "30", "50"]}
            onChange={setMinimumPitches} />
        </div>} />,
    },
  ];
  const activeRows = dashboardRows.filter((row) => workspaceSectionIds[activeWorkspace].has(row.id));
  const activeComponentIds = new Set(activeRows.flatMap((row) => row.items));
  const show = (componentId) => activeComponentIds.has(componentId) && visible(componentId);
  const activeWorkspaceDetails = workspaces.find(({ id }) => id === activeWorkspace) || workspaces[0];
  const gameDayRows = streamAnalysis.displayRows.slice(0, 6);
  const gameDayComparisonRows = fantasyAnalysis.displayRows
    .filter((row) => hasNumber(row.expected_whiff_rate) && hasNumber(row.whiff_rate))
    .slice(0, 6);
  const comparisonCeiling = Math.max(
    0.4,
    ...gameDayComparisonRows.flatMap((row) => [Number(row.expected_whiff_rate), Number(row.whiff_rate)]),
  );
  const coverageFacts = [
    { label: t("Pitches"), value: compact(analysis.totalPitches) },
    { label: t("Pitchers"), value: compact(analysis.pitchers) },
    { label: t("Swings"), value: compact(analysis.swings) },
    { label: t("Batted-ball events"), value: compact(analysis.battedBalls) },
  ];
  const indexMetrics = [
    {
      id: "index-expected-whiff",
      title: t("Expected whiff"),
      description: t("Champion-model expected whiff rate on the untouched chronological holdout."),
      value: formatRate(modelAnalysis.whiffChampion?.predicted_rate),
      comparison: `${compact(modelAnalysis.whiffChampion?.test_rows)} ${t("swings")}`,
      sourceRows: modelAnalysis.whiffChampion ? [modelAnalysis.whiffChampion] : [],
    },
    {
      id: "index-expected-hard-hit",
      title: t("Expected hard-hit"),
      description: t("Champion-model expected hard-hit rate on eligible holdout batted-ball events."),
      value: formatRate(modelAnalysis.hardHitChampion?.predicted_rate),
      comparison: `${compact(modelAnalysis.hardHitChampion?.test_rows)} ${t("batted-ball events")}`,
      sourceRows: modelAnalysis.hardHitChampion ? [modelAnalysis.hardHitChampion] : [],
    },
    {
      id: "index-holdout-sample",
      title: t("Holdout sample"),
      description: t("Non-unique scoring rows from the two champion holdouts; a pitch can contribute to both event sets."),
      value: compact(Number(modelAnalysis.whiffChampion?.test_rows || 0) + Number(modelAnalysis.hardHitChampion?.test_rows || 0)),
      comparison: t("Non-unique rows: whiff swings + hard-hit BBE"),
      sourceRows: [modelAnalysis.whiffChampion, modelAnalysis.hardHitChampion].filter(Boolean),
    },
    {
      id: "index-holdout-lift",
      title: t("Holdout lift"),
      description: t("Whiff champion test log-loss reduction versus its smoothed baseline."),
      value: `${Number(modelAnalysis.whiffChampion?.log_loss_reduction_pct || 0).toFixed(1)}%`,
      comparison: t("Test log-loss reduction"),
      sourceRows: modelAnalysis.whiffChampion ? [modelAnalysis.whiffChampion] : [],
    },
  ];

  const changeWorkspace = (workspaceId, focusTab = false) => {
    setActiveWorkspace(workspaceId);
    if (focusTab) window.requestAnimationFrame(() => document.getElementById(`mlb-workspace-${workspaceId}`)?.focus());
  };

  const handleWorkspaceKeyDown = (event) => {
    const currentIndex = workspaces.findIndex(({ id }) => id === activeWorkspace);
    const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    let nextIndex = direction ? (currentIndex + direction + workspaces.length) % workspaces.length : currentIndex;
    if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = workspaces.length - 1;
    else if (!direction) return;
    event.preventDefault();
    changeWorkspace(workspaces[nextIndex].id, true);
  };

  return <article className="page mlb-dashboard" lang={language}>
    <a className="mlb-skip-link" href="#mlb-workspace-panel">{t("Skip to dashboard evidence")}</a>
    <header className="mlb-command-header">
      <div className="mlb-command-brand" aria-label="Pitch Index, MLB pitch analytics">
        <span className="mlb-command-monogram" aria-hidden="true">PI</span>
        <div><h1>PITCH / INDEX</h1><p>MLB PITCH ANALYTICS · {analysis.lastDate ? `REVIEWED THROUGH ${analysis.lastDate}` : "REVIEWED DATA"}</p></div>
      </div>
      <nav className="mlb-workspace-nav" role="tablist" aria-label={t("Dashboard views")} onKeyDown={handleWorkspaceKeyDown}>
        {workspaces.map((workspace) => <button type="button" role="tab" key={workspace.id}
          id={`mlb-workspace-${workspace.id}`} aria-selected={activeWorkspace === workspace.id}
          aria-controls="mlb-workspace-panel" tabIndex={activeWorkspace === workspace.id ? 0 : -1}
          onClick={() => changeWorkspace(workspace.id)}>
          <span>{t(workspace.label)}</span>
        </button>)}
      </nav>
      <div className="mlb-language-switch" role="group" aria-label={t("Language")}>
        <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>EN</button>
        <button type="button" aria-pressed={language === "zh-TW"} onClick={() => setLanguage("zh-TW")}>繁中</button>
      </div>
    </header>

    {activeWorkspace === "pitch-lab" && <Filters sticky filters={localizedFilters} queries={queries} values={filters}
      onChange={setFilter} choiceIcons={{ team: mlbTeamLogos }} />}

    <div id="mlb-workspace-panel" role="tabpanel" aria-labelledby={`mlb-workspace-${activeWorkspace}`}
      className={`mlb-workspace-panel mlb-workspace-panel--${activeWorkspace}`}>
    <div className="mlb-workspace-heading">
      <span className="mlb-workspace-heading__index" aria-hidden="true">
        {String(workspaces.findIndex(({ id }) => id === activeWorkspace) + 1).padStart(2, "0")}
      </span>
      <div><h2>{t(activeWorkspaceDetails.label)}</h2><p>{t(activeWorkspaceDetails.description)}</p></div>
    </div>
    {activeWorkspace === "fantasy" && <section className="mlb-game-day" aria-labelledby="game-day-title">
      <div className="mlb-game-day__heading">
        <div>
          <p>{t("Fantasy decision workspace")}</p>
          <h2 id="game-day-title">{t("Game-Day Index")}</h2>
        </div>
        <p>{streamAnalysis.dateRange} · {t(streamProfile)} · {t(riskTolerance)}</p>
      </div>

      <div className="mlb-game-day__board">
        <DataComponent variant="plain" id="game-day-ledger" title={t("Ranked matchups")}
          queryId="matchup_stream_planner" kind="table" sourceRows={streamAnalysis.sourceRows}
          displayRows={gameDayRows}
          description={t("A source-backed queue for matchup review. Fit is a scenario ranking, not projected fantasy points.")}
          className="mlb-game-day-ledger">
          <ol className="mlb-matchup-ledger" data-reviewed-rows>
            {gameDayRows.length === 0 && <li className="mlb-matchup-ledger__empty">
              {t("No matchups meet the current view. Open Advanced filters to broaden the queue.")}
            </li>}
            {gameDayRows.map((row, index) => <li className="mlb-matchup-row" key={streamSlotKey(row)}>
              <span className="mlb-matchup-rank" aria-label={`${t("Rank")} ${index + 1}`}>{String(index + 1).padStart(2, "0")}</span>
              <div className="mlb-matchup-identity">
                <strong>{row.pitcher_name}</strong>
                <span>{row.pitcher_team} {language === "zh-TW" ? "對" : "vs"} {row.opponent_team}</span>
                <small>{row.game_time_display} · {row.venue_name || t("Venue pending")}</small>
              </div>
              <dl className="mlb-matchup-signals">
                <div><dt>{t("Fit")}</dt><dd>{row.personalized_fit_display}</dd></div>
                <div><dt>{t("Stream")}</dt><dd>{row.stream_score_display}</dd></div>
                <div><dt>{t("Skill")}</dt><dd>{row.fantasy_signal_display}</dd></div>
              </dl>
              <div className="mlb-matchup-context">
                <span>{t("Matchup")} {row.opponent_matchup_display}</span>
                <span>{t("Weather")} {row.weather_risk_display} · {row.precipitation_display}</span>
              </div>
              <div className="mlb-matchup-action">
                <strong>{row.strategy_action}</strong>
                <span>{row.probable_status_display}</span>
              </div>
            </li>)}
          </ol>
        </DataComponent>

        <aside className="mlb-decision-rail" aria-labelledby="decision-rail-title">
          <p>{t("Decision rail")}</p>
          <h3 id="decision-rail-title">{t("What clears today")}</h3>
          <dl>
            <div><dt>{t("Confirmed")}</dt><dd>{compact(streamAnalysis.confirmedRows.length)}</dd></div>
            <div><dt>{t("Scored")}</dt><dd>{compact(streamAnalysis.scoredRows.length)}</dd></div>
            <div className="mlb-decision-rail__focus"><dt>{t("Shortlist")}</dt><dd>{compact(streamAnalysis.shortlistRows.length)}</dd></div>
            <div><dt>{t("Weather flags")}</dt><dd>{compact(streamAnalysis.weatherRows.length)}</dd></div>
          </dl>
          <p className="mlb-decision-rail__note">
            {streamAnalysis.shortlistRows.length
              ? t("Review the shortlisted matchups against league settings and roster availability before acting.")
              : t("No matchup clears the 70-point fit threshold. Keep the queue visible; adjust strategy or risk only if your league context supports it.")}
          </p>
        </aside>
      </div>

      <div className="mlb-game-day-filters" aria-label={t("Game-day controls")}>
        <LocalizedDropdown language={language} label="Horizon" value={streamHorizon} choices={["Next 3 days", "Next 7 days"]}
          onChange={setStreamHorizon} />
        <LocalizedDropdown language={language} label="Pitching priority" value={streamProfile} choices={["Roto balance", "Strikeout upside", "Ratio protection"]}
          onChange={setStreamProfile} />
        <LocalizedDropdown language={language} label="Risk tolerance" value={riskTolerance} choices={["Low risk", "Balanced risk", "High risk"]}
          onChange={setRiskTolerance} />
        <details className="mlb-game-day-advanced">
          <summary>{t("Advanced")}</summary>
          <div>
            <LocalizedDropdown language={language} label="League format" value={leagueFormat} choices={["Categories", "Points skill proxy"]}
              onChange={setLeagueFormat} />
            <LocalizedDropdown language={language} label="Player pool" value={playerPoolFilter} choices={["All players", ...playerPoolStatuses]}
              onChange={setPlayerPoolFilter} />
            <LocalizedDropdown language={language} label="Planner view" value={streamView} choices={["Scored probables", "All scheduled slots", "Weather watch"]}
              onChange={setStreamView} />
          </div>
        </details>
      </div>

      <div className="mlb-game-day__lower">
        <DataComponent variant="plain" id="game-day-comparison" title={t("Expected vs observed whiff")}
          queryId="fantasy_pitcher_radar" kind="chart" sourceRows={fantasySourceRows}
          displayRows={gameDayComparisonRows}
          description={`${t(fantasyWindow)} · ${t(fantasyProfile)}. ${t("Solid bars show model expectation; outlined bars show the reviewed observed rate.")}`}
          className="mlb-game-day-comparison">
          <div className="mlb-comparison-chart" data-reviewed-rows>
            <div className="mlb-comparison-chart__legend"><span>{t("Expected")}</span><span>{t("Observed")}</span></div>
            {gameDayComparisonRows.map((row) => <div className="mlb-comparison-row" key={String(row.pitcher_id)}>
              <strong>{row.pitcher_name}</strong>
              <div className="mlb-comparison-track" aria-label={`${row.pitcher_name}: ${t("Expected")} ${formatRate(row.expected_whiff_rate)}, ${t("Observed")} ${formatRate(row.whiff_rate)}`}>
                <i className="mlb-comparison-bar mlb-comparison-bar--expected" style={{ height: `${(Number(row.expected_whiff_rate) / comparisonCeiling) * 100}%` }} />
                <i className="mlb-comparison-bar mlb-comparison-bar--observed" style={{ height: `${(Number(row.whiff_rate) / comparisonCeiling) * 100}%` }} />
              </div>
              <span>{formatRate(row.expected_whiff_rate)} / {formatRate(row.whiff_rate)}</span>
            </div>)}
          </div>
        </DataComponent>

        <DataComponent variant="plain" id="game-day-player-pool" title={t("Player pool queue")}
          queryId="matchup_stream_planner" kind="table" sourceRows={streamAnalysis.poolSourceRows}
          displayRows={streamAnalysis.poolCandidates.slice(0, 5)}
          description={t("Browser-only labels organize your research queue and never alter reviewed data or model scores.")}
          className="mlb-game-day-pool">
          <div className="mlb-game-day-pool__list" role="list" data-reviewed-rows>
            {streamAnalysis.poolCandidates.slice(0, 5).map((row) => <article role="listitem" key={String(row.pitcher_id)}>
              <div><strong>{row.pitcher_name}</strong><span>{row.pitcher_team} · {t("Fit")} {row.personalized_fit_display}</span></div>
              <button type="button" onClick={() => setPlayerPoolStatus(row.pitcher_id, "Watchlist")}
                aria-pressed={row.player_pool_status_key === "Watchlist"}>
                {row.player_pool_status_key === "Watchlist" ? t("Watching") : t("Watch")}
              </button>
            </article>)}
          </div>
        </DataComponent>
      </div>
    </section>}
    {activeWorkspace === "compare" && <PitcherComparison language={language} />}
    {activeWorkspace === "hitters" && <HitterWorkspace language={language} />}
    {activeRows.length > 0 && <SortableRegion id={`dashboard:mlb:${activeWorkspace}`} label={t("MLB pitch analytics blocks")}
      variant="canvas" spacing="standard" authoredRevision={7} columns={12} rows={activeRows}>
      {streamMetrics.filter(({ id }) => show(id)).map(({ id, title, description, value, comparison, sourceRows: metricRows }) =>
        <SortableItem key={id} id={id} label={title} kind="metric" span={3} minSpan={2}>
          <MetricCard id={id} title={title} queryId="matchup_stream_planner" sourceRows={metricRows}
            description={description} value={value} comparison={comparison} />
        </SortableItem>)}

      {show("stream-player-pool") && <SortableItem id="stream-player-pool" label={t("Fantasy player pool manager")} kind="table" span={12} minSpan={8}>
        <DataComponent variant="card" id="stream-player-pool" title={t("Player pool manager")}
          queryId="matchup_stream_planner" kind="table" sourceRows={streamAnalysis.poolSourceRows}
          displayRows={streamAnalysis.classifiedRows}
          description={t("Classify upcoming probable pitchers as Available, My roster, Watchlist, or Unavailable. Labels stay in this browser and only filter your decision workspace; they never change reviewed MLB data or model scores.")}
          className="mlb-player-pool-component">
          <div className="mlb-player-pool">
            <div className="mlb-player-pool__controls" role="group" aria-label={t("Classify an upcoming pitcher")}>
              <LocalizedDropdown language={language} label="Pitcher to classify" value={effectivePoolCandidate}
                choices={streamAnalysis.poolCandidates.length
                  ? streamAnalysis.poolCandidates.map((row) => row.candidate_label)
                  : ["No scored probable pitchers"]}
                onChange={setPoolCandidate} />
              <LocalizedDropdown language={language} label="Set player status" value={poolDraftStatus} choices={playerPoolStatuses}
                onChange={setPoolDraftStatus} />
              <button type="button" className="mlb-player-pool__save" onClick={savePlayerPoolStatus}
                disabled={streamAnalysis.poolCandidates.length === 0}>{t("Save label")}</button>
            </div>
            <div className="mlb-player-pool__summary" aria-live="polite">
              <strong>{streamAnalysis.classifiedRows.length}</strong>
              <span>{t("upcoming pitchers classified")}</span>
              <span>{t("Use the Player pool filter above to isolate actionable names.")}</span>
            </div>
            <div className="mlb-player-pool__list" role="list" data-reviewed-rows>
              {streamAnalysis.classifiedRows.length === 0 && <p className="mlb-player-pool__empty">
                {t("No player labels yet. Select a probable pitcher, assign a status, and save it here.")}
              </p>}
              {streamAnalysis.classifiedRows.map((row) => <article className="mlb-player-pool__row" role="listitem"
                key={String(row.pitcher_id)}>
                <div>
                  <strong>{row.pitcher_name}</strong>
                  <span>{row.pitcher_team} · {language === "zh-TW" ? "對" : "vs"} {row.opponent_team} · {row.game_date}</span>
                </div>
                <div className="mlb-player-pool__status">
                  <span>{row.player_pool_status}</span>
                  <button type="button" onClick={() => removePlayerPoolStatus(row.pitcher_id)}
                    aria-label={language === "zh-TW" ? `移除 ${row.pitcher_name} 的球員池標籤` : `Remove ${row.pitcher_name} player-pool label`}>{t("Remove")}</button>
                </div>
              </article>)}
            </div>
          </div>
        </DataComponent>
      </SortableItem>}

      {show("stream-planner-chart") && <SortableItem id="stream-planner-chart" label={t("Personalized stream fit leaders")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="stream-planner-chart" title={t("Personalized matchup fit")}
          queryId="matchup_stream_planner" kind="chart" chart={streamChart}
          sourceRows={streamAnalysis.chartSourceRows} displayRows={streamAnalysis.chartRows}
          description={language === "zh-TW"
            ? `${streamAnalysis.dateRange}。${t(leagueFormat)} · ${t(streamProfile)} · ${t(riskTolerance)}。適配度是在不變的基礎串流分數上疊加的透明情境排名，不是 Fantasy 積分預測。`
            : `${streamAnalysis.dateRange}. ${leagueFormat} · ${streamProfile} · ${riskTolerance}. Fit is a transparent scenario ranking layered on the unchanged base Stream Score, not projected fantasy points.`}
          className="mlb-chart-card mlb-stream-chart">
          <ChartRenderer spec={streamChart} rows={streamAnalysis.chartRows} height={372}
            {...chartProps("stream-planner-chart")} />
        </DataComponent>
      </SortableItem>}

      {show("stream-planner-table") && <SortableItem id="stream-planner-table" label={t("Upcoming stream planner table")} kind="table" span={7} minSpan={5}>
        <DataComponent variant="card" id="stream-planner-table" title={t("Upcoming pitcher matchups")}
          queryId="matchup_stream_planner" kind="table" sourceRows={streamAnalysis.sourceRows}
          displayRows={streamAnalysis.displayRows}
          description={language === "zh-TW"
            ? "類別制使用所選投手策略；積分制技能代理由 60% 所選策略與 40% 三振上限組成。低風險與平衡風險會扣除可見的天氣、樣本與降溫趨勢折扣，高風險則不扣分。基礎串流分數維持不變；在納入聯盟專屬權重、工作量、勝投與優質先發前，積分制仍不是完整預測。"
            : "Categories uses the chosen pitching profile. Points skill proxy blends 60% chosen profile with 40% strikeout upside. Low and balanced risk subtract visible weather, sample, and cooling-trend haircuts; high risk applies none. The base Stream Score remains unchanged, and points is not a full projection until league-specific values, workload, wins, and quality starts are modeled."}
          className="mlb-prediction-table mlb-stream-table">
          <DataTable rows={streamAnalysis.displayRows} columns={localizedStreamPlannerColumns}
            compactColumns={["player_pool_status", "opponent_team", "personalized_fit_display", "strategy_action", "stream_score_display", "fantasy_signal_display", "opponent_matchup_display", "precipitation_display"]}
            compactNumbers={false} pageSize={10}
            label={language === "zh-TW"
              ? `${t(leagueFormat)}、${t(streamProfile)}、${t(riskTolerance)}的投手對戰，日期 ${streamAnalysis.dateRange}`
              : `${leagueFormat}, ${streamProfile}, ${riskTolerance} pitcher matchups for ${streamAnalysis.dateRange}`} />
        </DataComponent>
      </SortableItem>}

      {metrics.filter(({ id }) => show(id)).map(({ id, title, description, value, comparison }) =>
        <SortableItem key={id} id={id} label={title} kind="metric" span={id === "pitch-count" ? 4 : 2} minSpan={2}>
          <MetricCard id={id} title={title} queryId="pitch_summary" sourceRows={sourceRows}
            description={description} value={value} comparison={comparison} />
        </SortableItem>)}

      {show("fantasy-insight-board") && <SortableItem id="fantasy-insight-board" label={t("Fantasy decision board")} kind="table" span={12} minSpan={8}>
        <DataComponent variant="card" padding="spacious" id="fantasy-insight-board" title={t("Latest research priorities")}
          queryId="fantasy_pitcher_radar" kind="table" sourceRows={fantasyAnalysis.insightRows}
          displayRows={fantasyAnalysis.insightRows}
          description={language === "zh-TW"
            ? `${t(fantasyWindow)}與${t(fantasyProfile)}的每日研究佇列。進行名單操作前，請確認聯盟設定、球員可用性、角色與對手賽程。`
            : `A daily research queue for ${fantasyWindow.toLowerCase()} and ${fantasyProfile.toLowerCase()}. Verify league settings, availability, role, and opponent schedule before making a roster move.`}
          className="mlb-insight-component">
          <div className="mlb-insight-board" role="list" data-reviewed-rows>
            {fantasyAnalysis.insightRows.length === 0 && <p className="mlb-insight-empty">
              {t("No pitchers meet the current workload and evidence thresholds. Broaden the workload filter or select a longer window.")}
            </p>}
            {fantasyAnalysis.insightRows.map((row) => <article className="mlb-insight-item" role="listitem"
              key={`${row.insightType}:${row.pitcher_id}`}>
              <div className="mlb-insight-item__topline">
                <span className="mlb-insight-type">{t(row.insightType)}</span>
                <span className="mlb-research-action">{t(row.research_action)}</span>
              </div>
              <h3>{row.pitcher_name}</h3>
              <p className="mlb-insight-identity">{row.pitcher_team} · {t(row.role_hint)}</p>
              <p className="mlb-insight-rationale">{row.rationale}</p>
              <dl className="mlb-insight-stats">
                <div><dt>{t("Skill signal")}</dt><dd>{Number(row.fantasy_signal).toFixed(1)}</dd></div>
                <div><dt>{t("Trend")}</dt><dd>{t(row.trend_status)}</dd></div>
                <div><dt>{t("Evidence")}</dt><dd>{t(row.sample_strength)}</dd></div>
              </dl>
            </article>)}
          </div>
        </DataComponent>
      </SortableItem>}

      {fantasyMetrics.filter(({ id }) => show(id)).map(({ id, title, description, value, comparison, sourceRows: metricRows }) =>
        <SortableItem key={id} id={id} label={title} kind="metric" span={4} minSpan={3}>
          <MetricCard id={id} title={title} queryId="fantasy_pitcher_radar" sourceRows={metricRows}
            description={description} value={value} comparison={comparison} />
        </SortableItem>)}

      {show("fantasy-radar-chart") && <SortableItem id="fantasy-radar-chart" label={t("Fantasy pitching skill leaders")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="fantasy-radar-chart" title={language === "zh-TW" ? `${t(fantasyProfile)}領先者` : `${fantasyProfile} leaders`} queryId="fantasy_pitcher_radar"
          kind="chart" chart={fantasyChart} sourceRows={fantasyAnalysis.displayRows} displayRows={fantasyAnalysis.chartRows}
          description={language === "zh-TW"
            ? `${t(fantasyWindow)}至 ${fantasyAnalysis.windowEnd}。顯示 ${fantasyAnalysis.qualifiedCount} 位符合${t(fantasyRole)}條件的投手；0–100 訊號用於比較投球技能，不是 Fantasy 積分預測。`
            : `${fantasyWindow} through ${fantasyAnalysis.windowEnd}. Showing ${fantasyAnalysis.qualifiedCount} qualified ${fantasyRole.toLowerCase()}; the zero-to-100 signal compares pitching skills and is not projected fantasy points.`}
          className="mlb-chart-card mlb-fantasy-chart">
          <ChartRenderer spec={fantasyChart} rows={fantasyAnalysis.chartRows} height={372} {...chartProps("fantasy-radar-chart")} />
        </DataComponent>
      </SortableItem>}

      {show("fantasy-radar-table") && <SortableItem id="fantasy-radar-table" label={t("Fantasy pitching radar table")} kind="table" span={7} minSpan={5}>
        <DataComponent variant="card" id="fantasy-radar-table" title={t("Recent pitching skill detail")} queryId="fantasy_pitcher_radar"
          kind="table" sourceRows={fantasyAnalysis.displayRows} displayRows={fantasyAnalysis.displayRows}
          description={t("Model expectations are combined with recent K−BB%, chase rate, and walk suppression. Workload, sample size, and previous-window movement remain visible for fantasy streaming review.")}
          className="mlb-prediction-table mlb-fantasy-table">
          <DataTable rows={fantasyAnalysis.displayRows} columns={localizedFantasyRadarColumns}
            compactColumns={["rank", "games", "pitches"]} compactNumbers={false} pageSize={10}
            label={language === "zh-TW" ? `${t(fantasyWindow)}的${t(fantasyProfile)} Fantasy 投手雷達` : `${fantasyProfile} fantasy pitching radar for ${fantasyWindow.toLowerCase()}`} />
        </DataComponent>
      </SortableItem>}

      {modelMetrics.filter(({ id }) => show(id)).map(({ id, title, description, value, comparison, sourceRows: metricRows }) =>
        <SortableItem key={id} id={id} label={title} kind="metric" span={4} minSpan={3}>
          <MetricCard id={id} title={title} queryId="model_evaluation" sourceRows={metricRows}
            description={description} value={value} comparison={comparison} />
        </SortableItem>)}

      {show("model-lift") && <SortableItem id="model-lift" label={t("Out-of-time model lift")} kind="chart" span={7} minSpan={5}>
        <DataComponent variant="card" id="model-lift" title={t("Out-of-time model lift")} queryId="model_evaluation"
          kind="chart" chart={liftChart} sourceRows={modelSourceRows} displayRows={modelAnalysis.liftRows}
          description={language === "zh-TW"
            ? `相較各目標平滑基準，在未觸碰測試集上的 log loss 降幅百分比；越高越好。測試區間為 ${modelAnalysis.testRange}。`
            : `Percent reduction in untouched-test log loss versus each target's smoothed baseline. Higher is better; the test window is ${modelAnalysis.testRange}.`}
          className="mlb-chart-card mlb-model-chart">
          <ChartRenderer spec={liftChart} rows={modelAnalysis.liftRows} height={332} {...chartProps("model-lift")} />
        </DataComponent>
      </SortableItem>}

      {show("model-calibration") && <SortableItem id="model-calibration" label={t("Probability calibration")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="model-calibration" title={t("Probability calibration")} queryId="model_calibration"
          kind="chart" chart={calibrationChart} sourceRows={calibrationSourceRows} displayRows={calibrationDisplayRows}
          description={t("Observed versus predicted event rates in populated test bins. Curves closer to the ideal diagonal are better calibrated.")}
          className="mlb-chart-card mlb-model-chart">
          <ChartRenderer spec={calibrationChart} rows={calibrationDisplayRows} height={332} {...chartProps("model-calibration")} />
        </DataComponent>
      </SortableItem>}

      {show("model-leaderboard-chart") && <SortableItem id="model-leaderboard-chart" label={t("Model scoring leaders")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="model-leaderboard-chart" title={language === "zh-TW" ? `${t(predictionAnalysis.targetLabel)}領先者` : `${predictionAnalysis.targetLabel} leaders`} queryId="model_leaderboard"
          kind="chart" chart={leaderboardChart} sourceRows={predictionAnalysis.leaderboardRows} displayRows={predictionAnalysis.chartRows}
          description={language === "zh-TW"
            ? `依未觸碰測試區間的模型優勢排列${t(leaderboardEntity)}結果。正值代表預期揮空較多或預期強擊球較少；最低樣本數顯示於來源資料。`
            : `Top ${leaderboardEntity.toLowerCase()} results by model edge in the untouched test window. Positive means more expected whiffs or fewer expected hard hits than the target average; minimum sample is shown in the source data.`}
          className="mlb-chart-card mlb-leaderboard-chart">
          <ChartRenderer spec={leaderboardChart} rows={predictionAnalysis.chartRows} height={344} {...chartProps("model-leaderboard-chart")} />
        </DataComponent>
      </SortableItem>}

      {show("model-leaderboard-table") && <SortableItem id="model-leaderboard-table" label={t("Model scoring leaderboard table")} kind="table" span={7} minSpan={5}>
        <DataComponent variant="card" id="model-leaderboard-table" title={language === "zh-TW" ? `${t(leaderboardEntity)}排行榜` : `${leaderboardEntity} leaderboard`} queryId="model_leaderboard"
          kind="table" sourceRows={predictionAnalysis.leaderboardRows} displayRows={predictionAnalysis.leaderboardRows}
          description={language === "zh-TW"
            ? `${t(predictionAnalysis.targetLabel)}，條件分母為${t(predictionAnalysis.denominator)}。${predictionAnalysis.dateRange}。排名依模型預期，並保留實際結果供比較。`
            : `${predictionAnalysis.targetLabel}, conditional on ${predictionAnalysis.denominator}. ${predictionAnalysis.dateRange}. Rankings use model expectation; actual results are included for comparison.`}
          className="mlb-prediction-table">
          <DataTable rows={predictionAnalysis.leaderboardRows} columns={localizedModelLeaderboardColumns}
            compactColumns={["rank", "sample_size"]} compactNumbers={false} pageSize={10}
            label={language === "zh-TW" ? `${t(predictionAnalysis.targetLabel)}${t(leaderboardEntity)}排行榜` : `${predictionAnalysis.targetLabel} ${leaderboardEntity.toLowerCase()} leaderboard`} />
        </DataComponent>
      </SortableItem>}

      {show("latest-pitch-predictions") && <SortableItem id="latest-pitch-predictions" label={t("Latest pitch predictions")} kind="table" span={12} minSpan={6}>
        <DataComponent variant="card" id="latest-pitch-predictions" title={t("Latest scored pitches")} queryId="pitch_model_predictions"
          kind="table" sourceRows={predictionAnalysis.latestRows} displayRows={predictionAnalysis.latestRows}
          description={language === "zh-TW"
            ? `最新內嵌的${t(predictionAnalysis.targetLabel)}分數，條件分母為${t(predictionAnalysis.denominator)}。完整投球層級測試分數仍保留在 Parquet 產出中。`
            : `Latest embedded ${predictionAnalysis.targetLabel.toLowerCase()} scores, conditional on ${predictionAnalysis.denominator}. Full pitch-level test scores remain in the parquet artifacts.`}
          className="mlb-prediction-table">
          <DataTable rows={predictionAnalysis.latestRows} columns={localizedPitchPredictionColumns}
            compactColumns={["count_state"]} compactNumbers={false} pageSize={10}
            label={language === "zh-TW" ? `最新${t(predictionAnalysis.targetLabel)}投球分數` : `Latest ${predictionAnalysis.targetLabel.toLowerCase()} pitch scores`} />
        </DataComponent>
      </SortableItem>}

      {show("pitch-usage") && <SortableItem id="pitch-usage" label={t("Pitch usage")} kind="chart" span={4} minSpan={3}>
        <DataComponent variant="card" id="pitch-usage" title={t("Pitch usage")} queryId="pitch_summary"
          kind="chart" chart={usageChart} sourceRows={sourceRows} displayRows={analysis.pitchUsageRows}
          description={t("Reviewed pitch counts by pitch type in the current filtered scope.")}
          className="mlb-chart-card">
          <ChartRenderer spec={usageChart} rows={analysis.pitchUsageRows} height={248} {...chartProps("pitch-usage")} />
        </DataComponent>
      </SortableItem>}

      {show("outcome-rates") && <SortableItem id="outcome-rates" label={t("Outcome rates by pitch")} kind="chart" span={8} minSpan={4}>
        <DataComponent variant="card" id="outcome-rates" title={t("Outcome rates by pitch")} queryId="pitch_summary"
          kind="chart" chart={outcomesChart} sourceRows={sourceRows} displayRows={analysis.outcomeRows}
          description={t("Whiff, chase, and hard-hit rates for the eight most-used pitches; each rate retains its own denominator.")}
          className="mlb-chart-card">
          <ChartRenderer spec={outcomesChart} rows={analysis.outcomeRows} height={248} {...chartProps("outcome-rates")} />
        </DataComponent>
      </SortableItem>}

      {show("pitch-mix-by-season") && <SortableItem id="pitch-mix-by-season" label={t("Pitch mix by season")} kind="chart" span={7} minSpan={4}>
        <DataComponent variant="card" id="pitch-mix-by-season" title={t("Pitch mix by season")} queryId="pitch_summary"
          kind="chart" chart={seasonMixChart} sourceRows={sourceRows} displayRows={analysis.seasonPitchMixRows}
          description={t("Pitch-type share within each reviewed season in the current filtered scope. Less-used pitch types are grouped as Other in the chart only.")}
          className="mlb-chart-card mlb-chart-card--arsenal">
          <ChartRenderer spec={seasonMixChart} rows={analysis.seasonPitchMixRows} height={286} {...chartProps("pitch-mix-by-season")} />
        </DataComponent>
      </SortableItem>}

      {show("velocity-whiff-profile") && <SortableItem id="velocity-whiff-profile" label={t("Velocity and whiff profile")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="velocity-whiff-profile" title={t("Velocity and whiff profile")} queryId="pitch_summary"
          kind="chart" chart={velocityProfileChart} sourceRows={sourceRows} displayRows={analysis.velocityWhiffRows}
          description={t("Pitch-count-weighted average velocity and whiff rate by pitch type; color identifies the reviewed pitch family.")}
          className="mlb-chart-card mlb-chart-card--arsenal">
          <ChartRenderer spec={velocityProfileChart} rows={analysis.velocityWhiffRows} height={286} {...chartProps("velocity-whiff-profile")} />
        </DataComponent>
      </SortableItem>}

      {show("count-strategy") && <SortableItem id="count-strategy" label={t("Pitch usage by count")} kind="chart" span={7} minSpan={4}>
        <DataComponent variant="card" id="count-strategy" title={t("Pitch usage by count")} queryId="pitch_summary"
          kind="chart" chart={strategyChart} sourceRows={sourceRows} displayRows={analysis.countRows}
          description={t("Pitch-type usage within each ball-strike count for the eight most-used pitches.")}
          className="mlb-chart-card mlb-chart-card--tall">
          <ChartRenderer spec={strategyChart} rows={analysis.countRows} height={330} {...chartProps("count-strategy")} />
        </DataComponent>
      </SortableItem>}

      {show("location-density") && <SortableItem id="location-density" label={t("Plate-location density")} kind="chart" span={5} minSpan={4}>
        <DataComponent variant="card" id="location-density" title={t("Plate-location density")} queryId="location_density"
          kind="chart" chart={locationChart} sourceRows={locationSourceRows} displayRows={analysis.locationRows}
          description={t("Reviewed pitches in quarter-foot plate-location bins; locations beyond the displayed window are excluded.")}
          className="mlb-chart-card mlb-chart-card--tall">
          <ChartRenderer spec={locationChart} rows={analysis.locationRows} height={330} {...chartProps("location-density")} />
        </DataComponent>
      </SortableItem>}

      {show("pitcher-table") && <SortableItem id="pitcher-table" label={t("Pitcher comparison table")} kind="table" span={12} minSpan={6}>
        <DataComponent variant="card" id="pitcher-table" title={t("Pitcher comparison table")} queryId="pitch_summary"
          kind="table" sourceRows={sourceRows} displayRows={analysis.pitcherRows}
          description={language === "zh-TW" ? `目前篩選範圍內至少有 ${minimumPitches} 顆已審查投球的投手。${analysis.dateRange}。` : `Pitchers with at least ${minimumPitches} reviewed pitches in the current filtered scope. ${analysis.dateRange}.`}
          className="mlb-pitcher-table">
          <DataTable rows={analysis.pitcherRows} columns={localizedPitcherColumns} compactColumns={["pitch_count"]}
            compactNumbers={false} pageSize={10} label={t("Reviewed pitcher comparison")} />
        </DataComponent>
      </SortableItem>}
    </SortableRegion>}
    </div>
  </article>;
}
