"""Evaluation harness. Run with: python -m evals.run_eval

Both entry points here print reports containing arrows and em dashes, and
both can be run directly. A Windows console defaults to cp1252 and raises
UnicodeEncodeError on those, which once killed a complete run - several
minutes of paid model calls - at the final print. Setting the encoding here
covers every module in the package rather than each one remembering to.
"""
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # Not a real console (captured by pytest, piped, redirected).
        pass
