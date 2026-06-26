"""Validation tests for the request/response schemas."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from aisnekbox.models import EvalRequest, FileEncoding, FilePayload


def test_filepayload_rejects_path_traversal() -> None:
    for bad in ["../escape", "/abs/path", "a/../b", "dir//file", "back\\slash", "."]:
        with pytest.raises(ValidationError):
            FilePayload(path=bad, content="x")


def test_filepayload_accepts_nested_relative_path() -> None:
    payload = FilePayload(path="sub/dir/data.txt", content="hello")
    assert payload.decoded_bytes() == b"hello"


def test_filepayload_base64_roundtrip() -> None:
    raw = b"\x00\x01\x02binary"
    payload = FilePayload(
        path="bin.dat",
        content=base64.b64encode(raw).decode(),
        encoding=FileEncoding.BASE64,
    )
    assert payload.decoded_bytes() == raw


def test_filepayload_invalid_base64_raises() -> None:
    payload = FilePayload(path="bin.dat", content="not base64!!", encoding=FileEncoding.BASE64)
    with pytest.raises(ValueError, match="valid base64"):
        payload.decoded_bytes()


def test_eval_request_defaults() -> None:
    req = EvalRequest(input="print(1)")
    assert req.args == []
    assert req.files == []
    assert req.executable_path is None


def test_eval_request_rejects_overlong_arg() -> None:
    with pytest.raises(ValidationError):
        EvalRequest(input="x", args=["a" * 5000])
