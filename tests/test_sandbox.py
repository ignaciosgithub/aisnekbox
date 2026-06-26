"""Tests for the sandbox supervisor logic using a fake NsJail."""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path

import pytest

from aisnekbox.config import Settings
from aisnekbox.models import EvalRequest, FilePayload
from aisnekbox.sandbox import ENTRYPOINT_NAME, JAIL_HOME, Sandbox, SandboxError


def test_build_command_structure(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    cmd = sandbox.build_command("/work", sys.executable, ["--flag"])
    assert cmd[0] == settings.nsjail_binary
    assert "--bindmount" in cmd
    assert f"/work:{JAIL_HOME}" in cmd
    # Everything after "--" is the program to run inside the jail.
    tail = cmd[cmd.index("--") + 1 :]
    assert tail == [sys.executable, ENTRYPOINT_NAME, "--flag"]


def test_build_command_includes_log_when_path_given(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    cmd = sandbox.build_command("/work", sys.executable, [], log_path="/var/log/jail.log")
    assert "--log" in cmd
    assert cmd[cmd.index("--log") + 1] == "/var/log/jail.log"
    # The log flag precedes the bind mount and program separator.
    assert cmd.index("--log") < cmd.index("--bindmount") < cmd.index("--")


def test_build_command_omits_log_by_default(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    assert "--log" not in sandbox.build_command("/work", sys.executable, [])


def test_jail_diagnostics_logged_at_debug(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log_file = tmp_path / "jail.log"
    log_file.write_text("nsjail: launched", encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger="aisnekbox.sandbox"):
        Sandbox(settings)._log_jail_diagnostics(str(log_file))
    assert "nsjail: launched" in caplog.text
    # A missing file must not raise.
    Sandbox(settings)._log_jail_diagnostics(str(log_file) + ".missing")


def test_resolve_executable_allowlist(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    assert sandbox.resolve_executable(None) == settings.default_executable
    assert sandbox.resolve_executable(sys.executable) == sys.executable
    with pytest.raises(SandboxError):
        sandbox.resolve_executable("/bin/sh")


def test_execute_captures_stdout(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    result = sandbox.execute(EvalRequest(input="print('hello world')"))
    assert result.returncode == 0
    assert "hello world" in result.stdout


def test_execute_reports_nonzero_returncode(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    result = sandbox.execute(EvalRequest(input="import sys; sys.exit(3)"))
    assert result.returncode == 3


def test_execute_returns_created_files(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    code = "open('out.txt', 'w').write('produced')"
    result = sandbox.execute(EvalRequest(input=code))
    assert len(result.files) == 1
    produced = result.files[0]
    assert produced.path == "out.txt"
    assert base64.b64decode(produced.content) == b"produced"


def test_execute_does_not_return_entrypoint(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    result = sandbox.execute(EvalRequest(input="x = 1"))
    assert result.files == []


def test_execute_reads_uploaded_file(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    req = EvalRequest(
        input="print(open('data.txt').read())",
        files=[FilePayload(path="data.txt", content="injected")],
    )
    result = sandbox.execute(req)
    assert "injected" in result.stdout


def test_output_is_truncated(settings: Settings) -> None:
    small = settings.model_copy(update={"max_output_size": 50})
    sandbox = Sandbox(small)
    result = sandbox.execute(EvalRequest(input="print('A' * 1000)"))
    assert "[output truncated]" in result.stdout
    assert len(result.stdout) < 200


def test_input_size_limit(settings: Settings) -> None:
    tiny = settings.model_copy(update={"max_input_size": 5})
    sandbox = Sandbox(tiny)
    with pytest.raises(SandboxError, match="maximum allowed size"):
        sandbox.execute(EvalRequest(input="print('too long')"))


def test_uploaded_file_size_limit(settings: Settings) -> None:
    tiny = settings.model_copy(update={"max_file_size": 4})
    sandbox = Sandbox(tiny)
    req = EvalRequest(input="pass", files=[FilePayload(path="big.txt", content="123456")])
    with pytest.raises(SandboxError, match="too large"):
        sandbox.execute(req)


def test_total_upload_size_limit(settings: Settings) -> None:
    capped = settings.model_copy(update={"max_total_upload_size": 4})
    sandbox = Sandbox(capped)
    req = EvalRequest(
        input="pass",
        files=[
            FilePayload(path="a.txt", content="aaa"),
            FilePayload(path="b.txt", content="bbb"),
        ],
    )
    with pytest.raises(SandboxError, match="combined"):
        sandbox.execute(req)


def test_build_command_includes_nproc_rlimit(settings: Settings) -> None:
    sandbox = Sandbox(settings)
    cmd = sandbox.build_command("/work", sys.executable, [])
    assert "--rlimit_nproc" in cmd
    assert cmd[cmd.index("--rlimit_nproc") + 1] == str(settings.max_processes)


def test_missing_nsjail_binary_raises(settings: Settings) -> None:
    broken = settings.model_copy(update={"nsjail_binary": "/nonexistent/nsjail-binary"})
    sandbox = Sandbox(broken)
    with pytest.raises(SandboxError, match="not found"):
        sandbox.execute(EvalRequest(input="print(1)"))


def test_files_limit_caps_returned_files(settings: Settings) -> None:
    limited = settings.model_copy(update={"files_limit": 2})
    sandbox = Sandbox(limited)
    code = "\n".join(f"open('f{i}.txt','w').write('{i}')" for i in range(5))
    result = sandbox.execute(EvalRequest(input=code))
    assert len(result.files) == 2


def test_large_output_file_is_truncated(settings: Settings) -> None:
    capped = settings.model_copy(update={"max_file_size": 5})
    sandbox = Sandbox(capped)
    result = sandbox.execute(EvalRequest(input="open('big.txt','w').write('X' * 100)"))
    assert len(result.files) == 1
    assert result.files[0].size == 5
