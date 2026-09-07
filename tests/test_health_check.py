import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.health_check import inspect_health


class HealthCheckTests(unittest.TestCase):
    def check(self, state='success', age_date='2026-09-04', receipt_error=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'pipeline_status.json'
            path.write_text(json.dumps({'status':state}))
            before = path.read_bytes()
            with patch('src.health_check.dataset_identity', return_value={'mode':'full','data_through':age_date}), patch('src.health_check.verify_receipt', side_effect=receipt_error):
                result = inspect_health({'paths':{'outputs_dir':str(root)}}, datetime(2026,9,5,tzinfo=timezone.utc))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(root.iterdir())), 1)
            return result

    def test_current_verified_success(self):
        self.assertEqual(self.check()['exit_code'], 0)

    def test_old_and_running_require_attention(self):
        self.assertEqual(self.check(age_date='2026-09-01')['exit_code'], 1)
        self.assertEqual(self.check(state='running')['exit_code'], 1)

    def test_failed_or_tampered_is_error(self):
        self.assertEqual(self.check(state='failed')['exit_code'], 2)
        self.assertEqual(self.check(receipt_error=RuntimeError('Artifact changed'))['exit_code'], 2)

    def test_future_data_is_error(self):
        self.assertEqual(self.check(age_date='2026-09-06')['exit_code'], 2)
