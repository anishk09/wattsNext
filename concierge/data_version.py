"""A short, stable fingerprint of the data/ files that drive every answer —
included in the audit log so a judge (or a future debugging session) can
tell whether two answers used the same underlying data."""
import hashlib
import pathlib

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
_FILES = [
    "risk_model.json", "backtest.json", "data_quality.json",
    "cases.json", "sample.json", "labor_reference.json",
]


def _compute():
    h = hashlib.sha256()
    for name in _FILES:
        path = _DATA_DIR / name
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


VERSION = _compute()
