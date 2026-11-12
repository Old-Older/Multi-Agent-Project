"""Private local process runner; process ownership is scoped to one exec call.

Windows uses a kill-on-close Job Object. Its isolated Python bootstrap waits
for a byte on stdin before starting the requested command, so assignment to
the job happens before that command can create descendants. POSIX commands
start a new session; cleanup kills that session's original process group.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mas.sandbox.base import ExecResult


_WINDOWS_BOOTSTRAP = """\
import sys
if sys.stdin.buffer.read(1) != b'1':
    sys.exit(127)
import subprocess
try:
    result = subprocess.run(sys.argv[1:], stdin=subprocess.DEVNULL)
except OSError as exc:
    sys.stderr.buffer.write(('Cannot start command: ' + str(exc) + '\\n').encode('utf-8'))
    sys.exit(127)
# sys.exit converts through a signed C int on Windows. Preserve DWORD exit
# statuses (including crash codes) by passing their signed representation.
code = result.returncode
sys.exit(code if code < 2**31 else code - 2**32)
"""


class _WindowsJob:
    """Minimal Job Object binding; imported only on Windows."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p, wintypes.DWORD]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        self._api = api
        self._handle = api.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self._handle, 9, ctypes.byref(limits),
                                          ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        import ctypes

        # AssignProcessToJobObject requires SET_QUOTA and TERMINATE rights.
        process = self._api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._api.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._api.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def run_command(cmd: list[str], root: Path, timeout: float,
                      env: dict[str, str] | None) -> ExecResult:
    """Run without a shell, collect UTF-8 output, and always clean up the tree.

    A timeout returns code -1 and retains output already written. A launch
    failure returns code 127 with an explanation in stderr. Cancellation is
    re-raised after cleanup. Environment overrides inherit the host environment.
    """
    from mas.sandbox.base import ExecResult

    process_env = os.environ.copy()
    process_env.update(env or {})
    windows = os.name == "nt"
    job = None
    proc = None
    launch = None
    communication = None
    output = (b"", b"")
    timed_out = False
    launch_error = None

    async def cleanup() -> None:
        nonlocal proc, communication, output
        try:
            if proc is None and launch is not None:
                try:
                    proc = await launch
                except (OSError, asyncio.CancelledError):
                    pass
        finally:
            if job:
                job.close()  # also kills descendants after their parent has exited
        if proc is not None:
            if windows:
                # Also covers failures before the gated bootstrap joined its job.
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
            else:
                _kill_group(proc)
            if communication is None:
                communication = asyncio.create_task(proc.communicate())
            output = await communication

    try:
        options = dict(cwd=root, env=process_env, stdout=asyncio.subprocess.PIPE,
                       stderr=asyncio.subprocess.PIPE)
        if windows:
            job = _WindowsJob()
            # -I -S keeps workspace/user Python startup hooks out of the gate.
            # A venv's python.exe may itself spawn the real interpreter. Use
            # that interpreter directly so no child can predate job assignment.
            interpreter = getattr(sys, "_base_executable", sys.executable)
            argv = [interpreter, "-I", "-S", "-c", _WINDOWS_BOOTSTRAP, *cmd]
            options.update(stdin=asyncio.subprocess.PIPE, creationflags=0x08000000)
        else:
            argv = cmd
            options.update(stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
        launch = asyncio.create_task(asyncio.create_subprocess_exec(*argv, **options))
        # If cancellation arrives during startup, finally still obtains the
        # process handle and reaps it instead of abandoning a spawned process.
        proc = await asyncio.shield(launch)
        if job:
            job.assign(proc.pid)
        communication = asyncio.create_task(proc.communicate(b"1" if windows else None))
        try:
            output = await asyncio.wait_for(asyncio.shield(communication), timeout)
        except asyncio.TimeoutError:
            timed_out = True
    except OSError as exc:
        launch_error = str(exc)
    finally:
        # shield alone leaves its caller interruptible. Own cleanup separately
        # and keep awaiting it if stop()/wait_for() cancel this task repeatedly.
        cleaning = asyncio.create_task(cleanup())
        cancelled_during_cleanup = False
        while not cleaning.done():
            try:
                await asyncio.shield(cleaning)
            except asyncio.CancelledError:
                cancelled_during_cleanup = True
        cleaning.result()
        if cancelled_during_cleanup:
            raise asyncio.CancelledError

    stdout, stderr = (part.decode("utf-8", errors="replace") for part in output)
    if launch_error is not None:
        return ExecResult(127, stdout, f"Cannot start command: {launch_error}")
    if timed_out:
        return ExecResult(-1, stdout, stderr, timed_out=True)
    return ExecResult(proc.returncode, stdout, stderr)
