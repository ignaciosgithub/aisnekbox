"""Test the console entrypoint wires settings into uvicorn."""

from __future__ import annotations

from unittest import mock

from aisnekbox import __main__


def test_main_runs_uvicorn_with_settings() -> None:
    with mock.patch.object(__main__.uvicorn, "run") as run:
        __main__.main()
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0] == "aisnekbox.api.app:app"
    assert "host" in kwargs
    assert "port" in kwargs
