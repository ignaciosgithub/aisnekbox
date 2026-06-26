"""Runtime configuration for aisnekbox.

All settings have safe defaults and can be overridden through environment
variables prefixed with ``AISNEKBOX_`` (for example ``AISNEKBOX_CPU_TIME=5``).
Keeping configuration centralised and validated makes the security-relevant
limits auditable in a single place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directory shipped with the package that holds the default NsJail config.
_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_NSJAIL_CONFIG = _PACKAGE_ROOT.parent / "config" / "nsjail.cfg"


class Settings(BaseSettings):
    """Validated application settings.

    The limits below are defence-in-depth: NsJail enforces them inside the
    jail, and aisnekbox additionally enforces wall-clock and output limits in
    the supervising process.
    """

    model_config = SettingsConfigDict(env_prefix="AISNEKBOX_", env_file=None)

    # --- Networking / server ---
    host: str = Field(default="0.0.0.0", description="Bind address for the API server.")
    port: int = Field(default=8060, ge=1, le=65535, description="Listen port.")
    debug: bool = Field(default=False, description="Enable verbose debug logging.")

    # --- Sandbox executable ---
    nsjail_binary: str = Field(default="nsjail", description="Path to the NsJail executable.")
    nsjail_config: Path = Field(
        default=_DEFAULT_NSJAIL_CONFIG,
        description="Path to the NsJail protobuf-text configuration file.",
    )
    default_executable: str = Field(
        default="/usr/bin/python3",
        description="Default interpreter executed inside the jail.",
    )
    allowed_executables: tuple[str, ...] = Field(
        default=("/usr/bin/python3", "/usr/local/bin/python3"),
        description=(
            "Absolute paths a client is allowed to request via 'executable_path'. "
            "An allowlist prevents arbitrary binaries from being launched."
        ),
    )

    # --- Resource limits enforced by the supervisor ---
    cpu_time: int = Field(
        default=10, ge=1, le=300, description="CPU-time limit (seconds) inside the jail."
    )
    wall_time: int = Field(
        default=20,
        ge=1,
        le=600,
        description="Wall-clock timeout (seconds) before the supervisor kills NsJail.",
    )
    memory_limit_mb: int = Field(
        default=128, ge=16, le=4096, description="Address-space limit (MiB) inside the jail."
    )
    max_processes: int = Field(
        default=1, ge=1, le=64, description="Maximum number of processes/threads."
    )

    # --- I/O limits ---
    max_output_size: int = Field(
        default=1_000_000,
        ge=1024,
        description="Maximum captured output size (bytes) before truncation.",
    )
    memfs_size_mb: int = Field(
        default=32, ge=1, le=1024, description="Size (MiB) of the per-run tmpfs work dir."
    )
    max_input_size: int = Field(
        default=1_000_000, ge=1, description="Maximum accepted source length (bytes)."
    )

    # --- Memory file system (uploaded/returned files) ---
    files_limit: int = Field(
        default=10, ge=0, le=100, description="Maximum number of output files returned."
    )
    max_file_size: int = Field(
        default=1_000_000, ge=1, description="Maximum size (bytes) of a single file."
    )

    @field_validator("allowed_executables", mode="before")
    @classmethod
    def _split_executables(cls, value: object) -> object:
        """Allow a comma-separated string from the environment."""
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
