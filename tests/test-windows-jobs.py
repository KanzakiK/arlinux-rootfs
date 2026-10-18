"""Wait timeouts are not application exits; cancellation is job-scoped."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import windows


class WindowsJobsTest(unittest.TestCase):
    def test_timeout_retains_job_and_cancellation_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            response = dict(job='12345678-1234-1234-1234-123456789abc',
                            log=str(Path(temp)/'native.log'), exit=str(Path(temp)/'exit'))
            with patch.object(windows, 'request', return_value=response), \
                 patch.object(windows, 'guest_path', side_effect=Path), \
                 patch.object(windows, '_host_request', return_value={'ok': True, 'scope': 'launcher'}) as cancel:
                with self.assertRaises(windows.WindowsWaitTimeout) as failure:
                    windows.run(Path('/runtime'), Path('/prefix'), 'app.exe', timeout=0)
                cancel.assert_not_called()
                self.assertEqual(failure.exception.job, response['job'])
                failure.exception.cancel_launcher()
                cancel.assert_called_once_with({'operation': 'cancel-job', 'job': response['job']})

    def test_unbounded_application_wait_preserves_exit_status(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base/'log').write_text('application output')
            (base/'exit').write_text('17')
            response = dict(job='unused', log=str(base/'log'), exit=str(base/'exit'))
            with patch.object(windows, 'request', return_value=response), patch.object(windows, 'guest_path', side_effect=Path):
                result = windows.run(Path('/runtime'), Path('/prefix'), 'app.exe', capture=True, timeout=None)
                self.assertEqual(result.returncode, 17)
                self.assertEqual(result.stdout, 'application output')

    def test_invalid_job_cannot_reach_host(self):
        with patch.object(windows, '_host_request') as host:
            with self.assertRaises(ValueError):
                windows.cancel_job('../another-instance')
            host.assert_not_called()


unittest.main()
