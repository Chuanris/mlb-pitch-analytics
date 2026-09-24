import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";


function compactBytes(value) {
  return Buffer.byteLength(JSON.stringify(value));
}


export function measureDashboardPayload({ snapshotPath, htmlPath }) {
  const snapshotBuffer = readFileSync(snapshotPath);
  const htmlBuffer = readFileSync(htmlPath);
  const snapshot = JSON.parse(snapshotBuffer.toString("utf8"));
  const pitchSummary = snapshot?.queries?.pitch_summary;
  if (!pitchSummary || !Array.isArray(pitchSummary.rows)) {
    throw new Error("snapshot queries.pitch_summary.rows must be an array");
  }

  return {
    snapshotBytes: snapshotBuffer.byteLength,
    htmlBytes: htmlBuffer.byteLength,
    htmlGzipBytes: gzipSync(htmlBuffer, { level: 9 }).byteLength,
    pitchSummaryBytes: compactBytes(pitchSummary),
    pitchSummaryRows: pitchSummary.rows.length,
  };
}


export function evaluateDashboardPayload(metrics, budget) {
  const checks = [
    ["snapshotBytes", "snapshot_max_bytes", "bytes"],
    ["htmlBytes", "built_html_max_bytes", "bytes"],
    ["htmlGzipBytes", "built_html_gzip_max_bytes", "bytes"],
    ["pitchSummaryBytes", "pitch_summary_max_bytes", "bytes"],
    ["pitchSummaryRows", "pitch_summary_max_rows", "rows"],
  ];
  return checks.flatMap(([metricName, budgetName, unit]) => {
    const value = metrics[metricName];
    const limit = budget[budgetName];
    if (!Number.isFinite(limit) || limit <= 0) {
      throw new Error(`${budgetName} must be a positive number`);
    }
    return value > limit
      ? [`${metricName} is ${value} ${unit}; budget is ${limit} ${unit}`]
      : [];
  });
}


function argumentValue(name, fallback) {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
}


function main() {
  const snapshotPath = resolve(argumentValue("--snapshot", "dashboard/src/data.json"));
  const htmlPath = resolve(argumentValue("--html", "dashboard/dist/index.html"));
  const configPath = resolve(argumentValue("--config", "config/dashboard_performance.json"));
  const budget = JSON.parse(readFileSync(configPath, "utf8"));
  const metrics = measureDashboardPayload({ snapshotPath, htmlPath });
  const violations = evaluateDashboardPayload(metrics, budget);
  process.stdout.write(`${JSON.stringify({ metrics, budget, violations }, null, 2)}\n`);
  if (violations.length) process.exitCode = 1;
}


const entrypoint = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === entrypoint) main();
