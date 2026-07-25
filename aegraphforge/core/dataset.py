"""
dataset.py -- CSV ingestion and column type inference.

No pandas dependency: the whole app needs only PySide6 at runtime, which
keeps it easy to drop next to an AE install or bundle with PyInstaller.

A Column knows its own kind (NUMERIC / DATE / CATEGORY / TEXT) and exposes
a `numeric` view so every downstream stage (scales, geometry, JSX) can treat
everything uniformly as floats.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

NUMERIC = "numeric"
DATE = "date"
CATEGORY = "category"
TEXT = "text"

# Ordered most-specific first. %-style so we can use strptime.
_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%Y-%m",
    "%Y",
]

_NUM_RE = re.compile(r"^\s*[-+]?(\d{1,3}(,\d{3})+|\d*)(\.\d+)?([eE][-+]?\d+)?\s*$")
_CURRENCY = str.maketrans("", "", "$£€¥%,\u00a0 ")


def _try_number(s: str) -> Optional[float]:
    if s is None:
        return None
    t = s.strip()
    if not t:
        return None
    neg = False
    # accounting negatives: (1,234.5)
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = t.translate(_CURRENCY)
    if not t or t in {"-", "+", ".", "NA", "N/A", "nan", "NaN", "null", "NULL"}:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return -v if neg else v


def _try_date(s: str) -> Optional[_dt.datetime]:
    if not s:
        return None
    t = s.strip()
    if not t:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def decimal_year(d: _dt.datetime) -> float:
    """2001-01-10 -> 2001.0247. Matches the YEARS array convention in the
    reference scripts (year + (day_of_year - 1) / days_in_year)."""
    start = _dt.datetime(d.year, 1, 1)
    end = _dt.datetime(d.year + 1, 1, 1)
    return d.year + (d - start).total_seconds() / (end - start).total_seconds()


def year_to_datetime(v: float) -> _dt.datetime:
    y = int(math.floor(v))
    start = _dt.datetime(y, 1, 1)
    end = _dt.datetime(y + 1, 1, 1)
    return start + (end - start) * (v - y)


@dataclass
class Column:
    name: str
    raw: List[str]
    kind: str = TEXT
    numeric: List[Optional[float]] = field(default_factory=list)
    dates: List[Optional[_dt.datetime]] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)   # ordered unique levels
    _cat_index: Dict[str, int] = field(default_factory=dict, repr=False)

    # ---- introspection -------------------------------------------------
    @property
    def is_plottable(self) -> bool:
        """Can this column drive a continuous axis?"""
        return self.kind in (NUMERIC, DATE)

    @property
    def n_valid(self) -> int:
        return sum(1 for v in self.numeric if v is not None)

    def finite(self) -> List[float]:
        return [v for v in self.numeric if v is not None]

    def value_range(self):
        vals = self.finite()
        if not vals:
            return (0.0, 1.0)
        lo, hi = min(vals), max(vals)
        if lo == hi:
            pad = abs(lo) * 0.1 or 1.0
            return (lo - pad, hi + pad)
        return (lo, hi)

    def category_of(self, row: int) -> str:
        return self.raw[row].strip()

    def level_index(self, row: int) -> int:
        return self._cat_index.get(self.raw[row].strip(), 0)

    def display_at(self, row: int) -> str:
        if self.kind == DATE and self.dates[row] is not None:
            return self.dates[row].strftime("%Y-%m-%d")
        return self.raw[row]

    def summary(self) -> str:
        if self.kind == NUMERIC:
            lo, hi = self.value_range()
            return f"{self.n_valid} values   {lo:,.4g} .. {hi:,.4g}"
        if self.kind == DATE:
            ds = [d for d in self.dates if d]
            if not ds:
                return "no parsable dates"
            return f"{len(ds)} dates   {min(ds):%Y-%m-%d} .. {max(ds):%Y-%m-%d}"
        if self.kind == CATEGORY:
            shown = ", ".join(self.categories[:6])
            more = "" if len(self.categories) <= 6 else f" (+{len(self.categories)-6})"
            return f"{len(self.categories)} levels: {shown}{more}"
        return f"{len(self.raw)} text values"


@dataclass
class Dataset:
    columns: List[Column]
    path: str = ""

    # ---- access --------------------------------------------------------
    @property
    def n_rows(self) -> int:
        return len(self.columns[0].raw) if self.columns else 0

    @property
    def names(self) -> List[str]:
        return [c.name for c in self.columns]

    def col(self, name: str) -> Optional[Column]:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def numeric_names(self) -> List[str]:
        return [c.name for c in self.columns if c.kind == NUMERIC]

    def plottable_names(self) -> List[str]:
        return [c.name for c in self.columns if c.is_plottable]

    def category_names(self) -> List[str]:
        return [c.name for c in self.columns if c.kind == CATEGORY]

    def label_names(self) -> List[str]:
        """Anything usable as a per-point text label."""
        return [c.name for c in self.columns]

    # ---- loading -------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str, max_category_levels: int = 40) -> "Dataset":
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        return cls.from_text(text, path=path, max_category_levels=max_category_levels)

    @classmethod
    def from_text(cls, text: str, path: str = "", max_category_levels: int = 40) -> "Dataset":
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        rows = [r for r in reader if any(str(c).strip() for c in r)]
        if not rows:
            raise ValueError("CSV appears to be empty.")

        header = [h.strip() or f"Column_{i+1}" for i, h in enumerate(rows[0])]
        # de-duplicate header names
        seen: Dict[str, int] = {}
        for i, h in enumerate(header):
            if h in seen:
                seen[h] += 1
                header[i] = f"{h}_{seen[h]}"
            else:
                seen[h] = 0

        width = len(header)
        body = [r + [""] * (width - len(r)) for r in rows[1:]]

        columns: List[Column] = []
        for i, name in enumerate(header):
            raw = [str(r[i]).strip() for r in body]
            columns.append(_infer(name, raw, max_category_levels))
        return cls(columns=columns, path=path)


def _infer(name: str, raw: List[str], max_levels: int) -> Column:
    nonblank = [v for v in raw if v != ""]
    col = Column(name=name, raw=raw)
    if not nonblank:
        col.kind = TEXT
        col.numeric = [None] * len(raw)
        col.dates = [None] * len(raw)
        return col

    nums = [_try_number(v) for v in raw]
    n_num = sum(1 for v, r in zip(nums, raw) if v is not None and r != "")

    dates = [_try_date(v) for v in raw]
    n_date = sum(1 for v, r in zip(dates, raw) if v is not None and r != "")

    # Dates win over numbers when a clear majority parse (a bare "2011"
    # column is ambiguous; prefer NUMERIC there so it still scales linearly).
    if n_date >= 0.8 * len(nonblank) and n_date > 0 and not _looks_like_plain_number(nonblank):
        col.kind = DATE
        col.dates = dates
        col.numeric = [decimal_year(d) if d else None for d in dates]
        return col

    if n_num >= 0.8 * len(nonblank):
        col.kind = NUMERIC
        col.numeric = nums
        col.dates = [None] * len(raw)
        return col

    levels: List[str] = []
    index: Dict[str, int] = {}
    for v in raw:
        if v not in index:
            index[v] = len(levels)
            levels.append(v)
    col.dates = [None] * len(raw)
    if len(levels) <= max_levels:
        col.kind = CATEGORY
        col.categories = levels
        col._cat_index = index
        col.numeric = [float(index[v]) for v in raw]
    else:
        col.kind = TEXT
        col.numeric = [None] * len(raw)
    return col


def _looks_like_plain_number(values: Sequence[str]) -> bool:
    """Guard against treating a bare integer year column as a date."""
    hits = 0
    for v in values[:50]:
        if _NUM_RE.match(v) and not any(ch in v for ch in "-/:"):
            hits += 1
    return hits >= 0.9 * min(len(values), 50)
