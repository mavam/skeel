"""Declarative agent skill management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skeel")
except PackageNotFoundError:  # pragma: no cover - package metadata exists in normal use
    __version__ = "0.0.0"
