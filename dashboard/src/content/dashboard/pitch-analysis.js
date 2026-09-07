// Pure aggregation over reviewed rows; no language or player-pool state.
function sum(rows, field) { return rows.reduce((total, row) => total + (Number(row[field]) || 0), 0); }
function safeRate(numerator, denominator) { return denominator > 0 ? numerator / denominator : null; }

function aggregatePitchUsage(rows) {
  const groups = new Map();
  const totalPitches = sum(rows, "pitch_count");
  rows.forEach((row) => {
    const key = row.pitch_name || row.pitch_type || "Unknown";
    const current = groups.get(key) ?? { pitch_name: key, pitch_count: 0 };
    current.pitch_count += Number(row.pitch_count) || 0;
    groups.set(key, current);
  });
  return [...groups.values()]
    .map((row) => ({ ...row, usage_rate: safeRate(row.pitch_count, totalPitches) }))
    .sort((left, right) => right.pitch_count - left.pitch_count);
}

function aggregateOutcomeRates(rows, includedPitches) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = row.pitch_name || row.pitch_type || "Unknown";
    if (!includedPitches.has(key)) return;
    const current = groups.get(key) ?? {
      pitch_name: key,
      pitch_count: 0,
      swings: 0,
      whiffs: 0,
      out_of_zone: 0,
      chases: 0,
      batted_balls: 0,
      hard_hits: 0,
    };
    current.pitch_count += Number(row.pitch_count) || 0;
    current.swings += Number(row.swing_count) || 0;
    current.whiffs += Number(row.whiff_count) || 0;
    current.out_of_zone += (Number(row.pitch_count) || 0) - (Number(row.in_zone_count) || 0);
    current.chases += Number(row.chase_count) || 0;
    current.batted_balls += Number(row.measured_batted_ball_count ?? row.batted_ball_count) || 0;
    current.hard_hits += Number(row.hard_hit_count) || 0;
    groups.set(key, current);
  });
  return [...groups.values()].map((row) => ({
    pitch_name: row.pitch_name,
    pitch_count: row.pitch_count,
    whiff_rate: safeRate(row.whiffs, row.swings),
    chase_rate: safeRate(row.chases, row.out_of_zone),
    hard_hit_rate: safeRate(row.hard_hits, row.batted_balls),
  })).sort((left, right) => right.pitch_count - left.pitch_count);
}

function aggregateCountStrategy(rows, includedPitches) {
  const totals = new Map();
  const groups = new Map();
  rows.forEach((row) => {
    const pitchName = row.pitch_name || row.pitch_type || "Unknown";
    const pitchCount = Number(row.pitch_count) || 0;
    totals.set(row.count_state, (totals.get(row.count_state) ?? 0) + pitchCount);
    if (!includedPitches.has(pitchName)) return;
    const key = `${row.count_state}\u0000${pitchName}`;
    groups.set(key, {
      count_state: row.count_state,
      pitch_name: pitchName,
      pitch_count: (groups.get(key)?.pitch_count ?? 0) + pitchCount,
    });
  });
  return [...groups.values()].map((row) => ({
    ...row,
    usage_rate: safeRate(row.pitch_count, totals.get(row.count_state)),
  }));
}

function quarterFootBin(value) {
  if (!Number.isFinite(Number(value))) return null;
  return (Math.round(Number(value) * 4) / 4).toFixed(2);
}

function aggregateLocation(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const plateX = Number(row.plate_x_bin);
    const plateZ = Number(row.plate_z_bin);
    if (!Number.isFinite(plateX) || !Number.isFinite(plateZ)
      || plateX < -2 || plateX > 2 || plateZ < 0 || plateZ > 5) return;
    const plateXBin = quarterFootBin(plateX);
    const plateZBin = quarterFootBin(plateZ);
    const key = `${plateXBin}\u0000${plateZBin}`;
    groups.set(key, {
      plate_x_bin: plateXBin,
      plate_z_bin: plateZBin,
      pitch_count: (groups.get(key)?.pitch_count ?? 0) + (Number(row.pitch_count) || 0),
    });
  });
  return [...groups.values()].sort((left, right) =>
    Number(left.plate_z_bin) - Number(right.plate_z_bin)
      || Number(left.plate_x_bin) - Number(right.plate_x_bin));
}

function aggregateSeasonPitchMix(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const season = String(row.season ?? "Unknown");
    const pitchName = row.pitch_name || row.pitch_type || "Unknown";
    const key = `${season}\u0000${pitchName}`;
    groups.set(key, {
      season,
      pitch_name: pitchName,
      pitch_count: (groups.get(key)?.pitch_count ?? 0) + (Number(row.pitch_count) || 0),
    });
  });
  return [...groups.values()].sort((left, right) =>
    left.season.localeCompare(right.season, undefined, { numeric: true })
      || right.pitch_count - left.pitch_count);
}

function aggregateVelocityWhiff(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const pitchName = row.pitch_name || row.pitch_type || "Unknown";
    const current = groups.get(pitchName) ?? {
      name: pitchName,
      pitch_family: row.pitch_family || "Other",
      pitch_count: 0,
      velocity_total: 0,
      velocity_count: 0,
      swings: 0,
      whiffs: 0,
    };
    current.pitch_count += Number(row.pitch_count) || 0;
    current.velocity_total += Number(row.velocity_total) || 0;
    current.velocity_count += Number(row.velocity_count) || 0;
    current.swings += Number(row.swing_count) || 0;
    current.whiffs += Number(row.whiff_count) || 0;
    groups.set(pitchName, current);
  });
  return [...groups.values()].map((row) => ({
    name: row.name,
    pitch_family: row.pitch_family,
    pitch_count: row.pitch_count,
    avg_velocity: row.velocity_count ? Number((row.velocity_total / row.velocity_count).toFixed(1)) : null,
    whiff_rate: safeRate(row.whiffs, row.swings),
  })).filter((row) => Number.isFinite(row.avg_velocity) && Number.isFinite(row.whiff_rate))
    .sort((left, right) => right.pitch_count - left.pitch_count);
}

function aggregatePitchers(rows, minimumPitches) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = String(row.pitcher_id);
    const current = groups.get(key) ?? {
      pitcher_name: row.pitcher_name || `Pitcher ${key}`,
      pitcher_team: row.pitcher_team || "—",
      pitcher_throws: row.pitcher_throws || "—",
      pitch_count: 0,
      velocity_total: 0,
      velocity_count: 0,
      in_zone: 0,
      swings: 0,
      whiffs: 0,
      out_of_zone: 0,
      chases: 0,
      batted_balls: 0,
      hard_hits: 0,
    };
    current.pitch_count += Number(row.pitch_count) || 0;
    current.velocity_total += Number(row.velocity_total) || 0;
    current.velocity_count += Number(row.velocity_count) || 0;
    current.in_zone += Number(row.in_zone_count) || 0;
    current.swings += Number(row.swing_count) || 0;
    current.whiffs += Number(row.whiff_count) || 0;
    current.out_of_zone += (Number(row.pitch_count) || 0) - (Number(row.in_zone_count) || 0);
    current.chases += Number(row.chase_count) || 0;
    current.batted_balls += Number(row.measured_batted_ball_count ?? row.batted_ball_count) || 0;
    current.hard_hits += Number(row.hard_hit_count) || 0;
    groups.set(key, current);
  });
  return [...groups.values()].filter((row) => row.pitch_count >= minimumPitches).map((row) => ({
    pitcher_name: row.pitcher_name,
    pitcher_team: row.pitcher_team,
    pitcher_throws: row.pitcher_throws,
    pitch_count: row.pitch_count,
    avg_velocity: row.velocity_count ? Number((row.velocity_total / row.velocity_count).toFixed(1)) : null,
    zone_rate: safeRate(row.in_zone, row.pitch_count),
    whiff_rate: safeRate(row.whiffs, row.swings),
    chase_rate: safeRate(row.chases, row.out_of_zone),
    hard_hit_rate: safeRate(row.hard_hits, row.batted_balls),
  })).sort((left, right) => right.pitch_count - left.pitch_count);
}


export function summarizePitches(rows) {
  const totals = { totalPitches:0, inZone:0, swings:0, whiffs:0, chases:0,
    battedBalls:0, measuredBattedBalls:0, hardHits:0, firstDate:null, lastDate:null };
  const pitchers = new Set();
  for (const row of rows) {
    totals.totalPitches += Number(row.pitch_count) || 0;
    totals.inZone += Number(row.in_zone_count) || 0;
    totals.swings += Number(row.swing_count) || 0;
    totals.whiffs += Number(row.whiff_count) || 0;
    totals.chases += Number(row.chase_count) || 0;
    totals.battedBalls += Number(row.batted_ball_count) || 0;
    totals.measuredBattedBalls += Number(row.measured_batted_ball_count ?? row.batted_ball_count) || 0;
    totals.hardHits += Number(row.hard_hit_count) || 0;
    if (row.pitcher_id != null) pitchers.add(row.pitcher_id);
    if (row.first_game_date && (!totals.firstDate || row.first_game_date < totals.firstDate)) totals.firstDate = row.first_game_date;
    if (row.last_game_date && (!totals.lastDate || row.last_game_date > totals.lastDate)) totals.lastDate = row.last_game_date;
  }
  return {...totals, pitchers:pitchers.size, outOfZone:totals.totalPitches-totals.inZone};
}

const pitchCache = new WeakMap();
const locationCache = new WeakMap();
export const EMPTY_PITCH_LAB = Object.freeze({ pitchUsageRows:[], outcomeRows:[], countRows:[],
  locationRows:[], seasonPitchMixRows:[], velocityWhiffRows:[], pitcherRows:[] });
export function pitchLabAnalysis(rows, locations) {
  let result = pitchCache.get(rows);
  if (!result) {
    const pitchUsageRows = aggregatePitchUsage(rows);
    const included = new Set(pitchUsageRows.slice(0,8).map(row=>row.pitch_name));
    result = {pitchUsageRows, outcomeRows:aggregateOutcomeRates(rows,included),
      countRows:aggregateCountStrategy(rows,included), seasonPitchMixRows:aggregateSeasonPitchMix(rows),
      velocityWhiffRows:aggregateVelocityWhiff(rows), pitcherRows:aggregatePitchers(rows,0)};
    pitchCache.set(rows,result);
  }
  let locationRows = locationCache.get(locations);
  if (!locationRows) { locationRows = aggregateLocation(locations); locationCache.set(locations,locationRows); }
  return {...result,locationRows};
}
