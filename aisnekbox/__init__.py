"""aisnekbox: a secure REST sandbox for executing untrusted Python code.

The package exposes :func:`aisnekbox.api.app.create_app` to build the ASGI
application and :class:`aisnekbox.sandbox.Sandbox` to run code in isolation.
"""

from importlib import metadata

try:
    __version__ = metadata.version("aisnekbox")
except metadata.PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
