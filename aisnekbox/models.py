"""Request and response schemas for the eval API.

These Pydantic models define and validate the public contract. Validation at
the edge (length limits, path checks) is the first layer of defence before any
untrusted input reaches the sandbox.
"""

from __future__ import annotations

import base64
import binascii
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FileEncoding(StrEnum):
    """How the ``content`` field of a :class:`FilePayload` is encoded."""

    UTF8 = "utf-8"
    BASE64 = "base64"


class FilePayload(BaseModel):
    """A file uploaded into, or returned from, the sandbox working directory."""

    path: str = Field(
        ...,
        max_length=255,
        description="Relative path within the sandbox working directory.",
    )
    content: str = Field(default="", description="File content (utf-8 text or base64).")
    encoding: FileEncoding = Field(
        default=FileEncoding.UTF8, description="Encoding used for 'content'."
    )

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        """Reject path traversal and absolute paths.

        Only simple relative paths are accepted so an uploaded file can never
        escape the per-run working directory.
        """
        if not value or value.strip() != value:
            raise ValueError("path must be a non-empty, trimmed string")
        if value.startswith("/") or "\\" in value:
            raise ValueError("path must be relative and use forward slashes")
        parts = value.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("path must not contain '.', '..' or empty segments")
        return value

    def decoded_bytes(self) -> bytes:
        """Return the file content as raw bytes, validating the encoding."""
        if self.encoding is FileEncoding.BASE64:
            try:
                return base64.b64decode(self.content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("content is not valid base64") from exc
        return self.content.encode("utf-8")


class EvalRequest(BaseModel):
    """Body of a ``POST /eval`` request."""

    input: str = Field(
        ...,
        description="Python source code executed as the entrypoint inside the sandbox.",
    )
    args: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="Additional arguments passed to the interpreter after the script.",
    )
    files: list[FilePayload] = Field(
        default_factory=list,
        max_length=20,
        description="Files written into the sandbox working directory before execution.",
    )
    executable_path: str | None = Field(
        default=None,
        description="Optional interpreter path; must be in the server allowlist.",
    )

    @field_validator("args")
    @classmethod
    def _validate_args(cls, value: list[str]) -> list[str]:
        for arg in value:
            if len(arg) > 4096:
                raise ValueError("each argument must be at most 4096 characters")
        return value


class FileResult(BaseModel):
    """A file produced by the sandbox and returned to the client."""

    path: str = Field(..., description="Relative path within the working directory.")
    size: int = Field(..., ge=0, description="Size of the file in bytes.")
    content: str = Field(..., description="Base64-encoded file content.")
    encoding: FileEncoding = Field(
        default=FileEncoding.BASE64, description="Encoding of 'content' (always base64)."
    )


class EvalResult(BaseModel):
    """Body of a ``POST /eval`` response."""

    stdout: str = Field(..., description="Combined stdout and stderr from the run.")
    returncode: int | None = Field(
        ...,
        description="Process exit code, or null if the process was killed (e.g. timeout).",
    )
    files: list[FileResult] = Field(
        default_factory=list, description="Files written by the sandboxed code."
    )
