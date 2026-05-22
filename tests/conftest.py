"""Test configuration.

We avoid importing the component as a package because that triggers
``custom_components/homekit_smart_sync/__init__.py``, which depends on
the real Home Assistant runtime — a heavy install we don't want in the
unit-test job.

Instead, we register a synthetic package (``_hss_pure``) whose
``__path__`` points at the component directory, then load individual
submodules through it. Relative imports like ``from .const import …``
inside those submodules resolve correctly because they see a real
parent package.

Integration tests, when added, will live under ``tests/integration/``
with their own conftest pulling in ``pytest-homeassistant-custom-component``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "homekit_smart_sync"
_PKG_NAME = "_hss_pure"

if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_COMPONENT_DIR)]
    sys.modules[_PKG_NAME] = _pkg


def _load(submodule: str):
    """Load `submodule.py` from the component dir under the shim package."""
    fq_name = f"{_PKG_NAME}.{submodule}"
    if fq_name in sys.modules:
        return sys.modules[fq_name]
    spec = importlib.util.spec_from_file_location(fq_name, _COMPONENT_DIR / f"{submodule}.py")
    assert spec and spec.loader, f"cannot locate {submodule}.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fq_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def naming():
    return _load("naming")


@pytest.fixture(scope="session")
def filtering():
    _load("const")  # filtering does `from .const import …`
    return _load("filtering")
