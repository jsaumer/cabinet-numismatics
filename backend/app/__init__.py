"""Cabinet backend. The version lives in pyproject.toml; read it from the
installed distribution metadata so there is a single source of truth."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cabinet-backend")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+dev"
