"""Agent-facing shim: `python3 scripts/selftest.py` is the documented command.

The real test lives in ``tests/selftest.py`` so the package keeps one canonical
test file; this module just forwards ``argv`` and the exit code.
"""
import os
import sys

sys.dont_write_bytecode = True  # keep the submitted tree free of __pycache__

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
TESTS = os.path.join(PKG, "tests")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import importlib.util

_spec = importlib.util.spec_from_file_location("_paper2deck_selftest",
                                              os.path.join(TESTS, "selftest.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["_paper2deck_selftest"] = _mod

if __name__ == "__main__":
    raise SystemExit(_mod.main(sys.argv[1:]))
