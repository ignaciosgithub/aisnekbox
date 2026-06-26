"""Sandboxed execution of untrusted Python code via NsJail.

Security model
--------------
Untrusted code never runs in the API process. For every request a fresh,
empty working directory is created and bind-mounted into an NsJail jail that:

* has **no network access** (a fresh, empty network namespace);
* runs in its own PID/IPC/UTS/mount/user namespaces;
* drops all capabilities and sets ``no_new_privs``;
* enforces CPU-time, address-space, file-size and process-count rlimits;
* exposes the host filesystem **read-only** except the per-run work dir.

The supervisor additionally enforces a wall-clock timeout (in case the jailed
process ignores CPU limits while sleeping) and truncates captured output.

This module deliberately keeps :meth:`Sandbox.build_command` free of side
effects so the exact argument vector handed to NsJail can be unit-tested
without a kernel.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .models import EvalRequest, EvalResult, FileEncoding, FileResult

logger = logging.getLogger(__name__)

# Name of the entrypoint script written into the work dir. It is excluded from
# the set of files returned to the client.
ENTRYPOINT_NAME = "_aisnekbox_main.py"

# Mount point of the writable work dir inside the jail.
JAIL_HOME = "/home"


class SandboxError(RuntimeError):
    """Raised when the sandbox cannot be set up or NsJail cannot be launched."""


@dataclass(frozen=True)
class _RunOutput:
    stdout: str
    returncode: int | None


class Sandbox:
    """Executes Python code inside an NsJail jail."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def resolve_executable(self, requested: str | None) -> str:
        """Return the interpreter path to use, enforcing the allowlist."""
        if requested is None:
            return self._settings.default_executable
        if requested not in self._settings.allowed_executables:
            raise SandboxError(f"executable_path not permitted: {requested!r}")
        return requested

    def build_command(self, work_dir: str, executable: str, args: list[str]) -> list[str]:
        """Build the NsJail argument vector (pure, no side effects)."""
        s = self._settings
        cmd: list[str] = [
            s.nsjail_binary,
            "--config",
            str(s.nsjail_config),
            "--cwd",
            JAIL_HOME,
            # Bind-mount the per-run work dir read-write as the jail home.
            "--bindmount",
            f"{work_dir}:{JAIL_HOME}",
            # Resource limits (override config defaults from settings).
            "--time_limit",
            str(s.wall_time),
            "--rlimit_cpu",
            str(s.cpu_time),
            "--rlimit_as",
            str(s.memory_limit_mb),
            "--rlimit_fsize",
            str(max(1, self._memfs_size_mb)),
            "--",
            executable,
            ENTRYPOINT_NAME,
            *args,
        ]
        return cmd

    def execute(self, request: EvalRequest) -> EvalResult:
        """Run ``request`` and return its result."""
        executable = self.resolve_executable(request.executable_path)
        self._validate_input(request)

        work_dir = tempfile.mkdtemp(prefix="aisnekbox-")
        try:
            self._populate(work_dir, request)
            before = self._snapshot(work_dir)
            cmd = self.build_command(work_dir, executable, request.args)
            logger.debug("launching nsjail: %s", " ".join(cmd))
            output = self._run(cmd)
            files = self._collect_files(work_dir, before)
            return EvalResult(stdout=output.stdout, returncode=output.returncode, files=files)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @property
    def _memfs_size_mb(self) -> int:
        return self._settings.memfs_size_mb

    def _validate_input(self, request: EvalRequest) -> None:
        if len(request.input.encode("utf-8")) > self._settings.max_input_size:
            raise SandboxError("input exceeds the maximum allowed size")

    def _populate(self, work_dir: str, request: EvalRequest) -> None:
        """Write the entrypoint and uploaded files into the work dir."""
        entrypoint = Path(work_dir) / ENTRYPOINT_NAME
        entrypoint.write_text(request.input, encoding="utf-8")

        for payload in request.files:
            data = payload.decoded_bytes()
            if len(data) > self._settings.max_file_size:
                raise SandboxError(f"uploaded file too large: {payload.path!r}")
            target = self._safe_join(work_dir, payload.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    @staticmethod
    def _safe_join(work_dir: str, relative: str) -> Path:
        """Join ``relative`` to ``work_dir`` and guarantee it stays inside it."""
        base = Path(work_dir).resolve()
        candidate = (base / relative).resolve()
        if base != candidate and base not in candidate.parents:
            raise SandboxError(f"refusing to write outside the sandbox: {relative!r}")
        return candidate

    @staticmethod
    def _snapshot(work_dir: str) -> dict[str, float]:
        """Map each existing file path to its modification time."""
        snapshot: dict[str, float] = {}
        for root, _dirs, names in os.walk(work_dir):
            for name in names:
                full = os.path.join(root, name)
                try:
                    snapshot[full] = os.path.getmtime(full)
                except OSError:
                    continue
        return snapshot

    def _run(self, cmd: list[str]) -> _RunOutput:
        """Launch NsJail and capture combined stdout/stderr with limits."""
        try:
            proc = subprocess.Popen(  # noqa: S603 - argv is fully constructed, no shell
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            raise SandboxError(
                f"NsJail binary not found: {self._settings.nsjail_binary!r}"
            ) from exc

        max_size = self._settings.max_output_size
        deadline = time.monotonic() + self._settings.wall_time + 5
        chunks: list[bytes] = []
        total = 0
        if proc.stdout is None:  # pragma: no cover - stdout is always a pipe
            raise SandboxError("Failed to capture sandbox output stream.")
        try:
            while True:
                if time.monotonic() > deadline:
                    self._terminate(proc)
                    break
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                if total < max_size:
                    chunks.append(chunk[: max_size - total])
                    total += len(chunk)
                # Keep draining the pipe so the child does not block on a full
                # buffer even after we stop storing output.
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            returncode = proc.returncode
        finally:
            if proc.stdout is not None:
                proc.stdout.close()

        text = b"".join(chunks).decode("utf-8", errors="replace")
        if total >= max_size:
            text += "\n[output truncated]"
        return _RunOutput(stdout=text, returncode=returncode)

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        """Best-effort termination of a runaway NsJail process."""
        for action in (proc.terminate, proc.kill):
            if proc.poll() is not None:
                return
            try:
                action()
                proc.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                continue

    def _collect_files(self, work_dir: str, before: dict[str, float]) -> list[FileResult]:
        """Return files created or modified during the run."""
        results: list[FileResult] = []
        entrypoint = os.path.join(work_dir, ENTRYPOINT_NAME)
        candidates: list[str] = []
        for root, _dirs, names in os.walk(work_dir):
            for name in names:
                full = os.path.join(root, name)
                if full == entrypoint:
                    continue
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                if full not in before or mtime > before[full]:
                    candidates.append(full)

        candidates.sort()
        for full in candidates[: self._settings.files_limit]:
            try:
                data = Path(full).read_bytes()
            except OSError:
                continue
            if len(data) > self._settings.max_file_size:
                data = data[: self._settings.max_file_size]
            rel = os.path.relpath(full, work_dir)
            results.append(
                FileResult(
                    path=rel,
                    size=len(data),
                    content=base64.b64encode(data).decode("ascii"),
                    encoding=FileEncoding.BASE64,
                )
            )
        return results
