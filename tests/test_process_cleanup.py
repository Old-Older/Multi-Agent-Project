"""Process status and cancellation regressions using real local subprocesses."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mas.sandbox import LocalSandbox


class ProcessCleanupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sandbox = LocalSandbox("coder", Path(self.tmp.name))

    @unittest.skipUnless(os.name == "nt", "DWORD exit codes are Windows-specific")
    async def test_preserves_high_bit_windows_exit_status(self):
        result = await self.sandbox.exec(
            [sys.executable, "-c", "import os; os._exit(-1073741819)"], timeout=5)
        self.assertEqual(result.returncode, 0xC0000005)
        self.assertFalse(result.timed_out)

    async def test_repeated_cancellation_during_startup_reaps_real_process(self):
        real_launch = asyncio.create_subprocess_exec
        started, release = asyncio.Event(), asyncio.Event()
        processes = []

        async def delayed_launch(*args, **kwargs):
            # Only delay delivery of the real handle. This deterministically
            # exposes the startup interval in which exec has not received it.
            process = await real_launch(*args, **kwargs)
            processes.append(process)
            started.set()
            await release.wait()
            return process

        with patch("mas.sandbox._process.asyncio.create_subprocess_exec", delayed_launch):
            running = asyncio.create_task(self.sandbox.exec(
                [sys.executable, "-c", "import time; time.sleep(30)"], timeout=10))
            try:
                await asyncio.wait_for(started.wait(), 5)
                running.cancel()
                await asyncio.sleep(0)
                running.cancel()
                await asyncio.sleep(0)
                self.assertFalse(running.done(), "cancellation must wait for process cleanup")
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(running, 5)
                self.assertIsNotNone(processes[0].returncode)
            finally:
                release.set()
                if not running.done():
                    running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                # A broken implementation must not leave a test subprocess.
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                    await process.communicate()


if __name__ == "__main__":
    unittest.main()
