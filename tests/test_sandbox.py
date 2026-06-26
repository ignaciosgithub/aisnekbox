"""Tests for the sandbox supervisor logic using a fake NsJail."""

from __future__ import annotations

import base64
import sys

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
