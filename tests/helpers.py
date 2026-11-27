"""Test helpers for the xiaomi-key daemon test suite."""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON_PATH = REPO_ROOT / "bin" / "xiaomi-key-daemon.py"

_loaded = {}


def load_daemon():
    """Import ``bin/xiaomi-key-daemon.py`` (its filename is not importable).

    The module has to be registered in ``sys.modules`` before execution:
    ``@dataclass`` resolves annotations through ``sys.modules[name]``.
    """
    if "module" not in _loaded:
        spec = importlib.util.spec_from_file_location("xiaomi_key_daemon",
                                                      DAEMON_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _loaded["module"] = module
    return _loaded["module"]
