"""Shared test fixtures.

Real NsJail requires elevated kernel privileges, so the test-suite substitutes
a *fake* NsJail. The fake parses the same ``--bindmount`` / ``--`` argument
layout that :meth:`Sandbox.build_command` produces and runs the entrypoint in
the bind-mounted directory. This exercises the full populate -> run ->
collect-files pipeline without a kernel sandbox, while a separate, skipped
integration test covers the real binary when available.
"""

from __future__ import annotations

import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from aisnekbox.config import Settings

FAKE_NSJAIL = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os
    import subprocess
    import sys

    argv = sys.argv[1:]
    work_dir = None
    i = 0
    cmd = []
    while i < len(argv):
        token = argv[i]
        if token == "--bindmount":
            work_dir = argv[i + 1].split(":", 1)[0]
            i += 2
            continue
        if token == "--":
            cmd = argv[i + 1 :]
            break
        # Skip flags that take a value.
        if token in ("--config", "--cwd", "--time_limit", "--rlimit_cpu",
                     "--rlimit_as", "--rlimit_fsize"):
            i += 2
            continue
        i += 1

    if not cmd or work_dir is None:
        sys.stderr.write("fake-nsjail: bad invocation\\n")
        sys.exit(2)

    proc = subprocess.run(cmd, cwd=work_dir)
    sys.exit(proc.returncode)
    """
)


@pytest.fixture
def fake_nsjail(tmp_path: Path) -> Path:
    """Create an executable fake nsjail and return its path."""
    path = tmp_path / "fake_nsjail.py"
    path.write_text(FAKE_NSJAIL, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def settings(fake_nsjail: Path) -> Settings:
    """Settings wired to the fake nsjail and the current interpreter."""
    return Settings(
        nsjail_binary=str(fake_nsjail),
        nsjail_config=Path(os.devnull),
        default_executable=sys.executable,
        allowed_executables=(sys.executable,),
        wall_time=10,
        cpu_time=5,
    )
