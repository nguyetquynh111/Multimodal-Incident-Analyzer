"""Make the repository root importable when pytest starts inside ``tests/``."""

from __future__ import annotations

from pathlib import Path
import sys
import warnings


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

warnings.filterwarnings(
    "ignore",
    message=r"builtin type.*has no __module__ attribute",
    category=DeprecationWarning,
)
