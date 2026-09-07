"""Read-only operational checks. Exit 0=pass, 1=attention, 2=error."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

from src.common import load_config, project_path
from src.artifact_lineage import dataset_identity, verify_receipt


def inspect_health(config, now=None, max_age_days=2):
    now = now or datetime.now(timezone.utc)
    checks = []
    def add(name, status, detail, action=''):
        checks.append(dict(check=name, status=status, detail=detail, action=action))
    output = project_path(config['paths']['outputs_dir'])
    try:
        identity = dataset_identity(config)
        age = (now.date() - datetime.fromisoformat(identity['data_through']).date()).days
        state = 'error' if age < 0 else 'attention' if age > max_age_days else 'pass'
        add('data_age', state, f"{identity['mode']} data through {identity['data_through']}; {age} calendar days old (UTC).",
            'Check the configured date range and game calendar before refreshing; age alone does not prove missing games.' if state != 'pass' else '')
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        try:
            verify_receipt(output / 'lineage/build_dashboard_snapshot.json', identity, config_hash)
            add('snapshot_lineage', 'pass', 'Snapshot and recursive artifact dependencies match the current dataset.')
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            add('snapshot_lineage', 'error', str(error), 'Rerun the appropriate pipeline workflow; do not reuse stale derived outputs.')
    except Exception as error:
        add('database', 'error', str(error), 'Check the database path and rebuild a versioned dataset.')
    try:
        status = json.loads((output / 'pipeline_status.json').read_text(encoding='utf-8'))
        state = status.get('status', 'unknown')
        severity = 'pass' if state == 'success' else 'error' if state in ('failed', 'interrupted') else 'attention'
        add('last_pipeline', severity, f"{state}; step={status.get('current_step')}; started={status.get('started_at_utc')}; finished={status.get('finished_at_utc')}",
            'Inspect logs and confirm no runner is active before rerunning. A running marker alone does not prove a process is alive.' if severity != 'pass' else '')
    except (OSError, ValueError, AttributeError) as error:
        add('last_pipeline', 'attention', str(error), 'No readable run status; inspect runner logs. Standalone stage runs do not update this record.')
    return dict(checked_at_utc=now.isoformat(), max_age_days=max_age_days, checks=checks,
                exit_code=2 if any(c['status']=='error' for c in checks) else 1 if any(c['status']=='attention' for c in checks) else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/pipeline_config.json')
    parser.add_argument('--max-age-days', type=int, default=2)
    args = parser.parse_args()
    if args.max_age_days < 0:
        parser.error('--max-age-days must be nonnegative')
    result = inspect_health(load_config(args.config), max_age_days=args.max_age_days)
    print(json.dumps(result, indent=2))
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
