import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  evaluateDashboardPayload,
  measureDashboardPayload,
} from "../../scripts/check_dashboard_payload.mjs";


test("payload budget reports the exact failing artifact and limit", () => {
  const directory = mkdtempSync(join(tmpdir(), "mlb-dashboard-budget-"));
  try {
    const snapshotPath = join(directory, "data.json");
    const htmlPath = join(directory, "index.html");
    writeFileSync(snapshotPath, JSON.stringify({
      queries: {
        pitch_summary: { rows: [{ pitch_count: 1 }] },
      },
    }));
    writeFileSync(htmlPath, "<main>reviewed dashboard</main>");

    const metrics = measureDashboardPayload({ snapshotPath, htmlPath });
    assert.equal(metrics.pitchSummaryRows, 1);
    assert.equal(metrics.snapshotBytes, 58);
    assert.equal(metrics.htmlBytes, 31);

    const violations = evaluateDashboardPayload(metrics, {
      snapshot_max_bytes: 57,
      built_html_max_bytes: 31,
      built_html_gzip_max_bytes: 100,
      pitch_summary_max_bytes: 100,
      pitch_summary_max_rows: 1,
    });
    assert.deepEqual(violations, [
      "snapshotBytes is 58 bytes; budget is 57 bytes",
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
