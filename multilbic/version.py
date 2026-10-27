"""
The version of the code that is running.

`importlib.metadata.version("multilbic")` gives the version recorded when
the package was last *installed*. MultiLBIC runs from its checkout with
`uv run --no-sync` (on the Pi, and in development), which skips that
install, so after a `git pull` the installed record can be several
versions behind the code: the window showed 0.5.3 while running 0.5.13,
and run files would have said the same. So the version comes from
`pyproject.toml` beside the package when there is one (a checkout, as
everywhere MultiLBIC runs today), and from the installed record only
when there is not (a wheel).
"""

from __future__ import annotations

import functools
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@functools.cache
def app_version() -> str:
    try:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        meta = project["project"]
        if meta.get("name") == "multilbic":
            return str(meta["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return version("multilbic")
    except PackageNotFoundError:
        return "unknown"
