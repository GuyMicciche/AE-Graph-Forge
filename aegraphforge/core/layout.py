"""Text metrics and legend packing.

The preview and the JSX generator must place the legend identically, and the
JSX side has no way to measure a font at build time. So both consume the
placement computed here, from an Arial advance-width table. The numbers are
Arial's own metrics in 1/1000 em, which is close enough to Helvetica and the
other fallbacks in the generated setFont() candidate list that a few pixels of
drift never shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

RGB = Tuple[float, float, float]

# Arial advance widths, units per 1000 em. Regular and bold differ mostly in
# the lowercase, and every label we draw is bold, so one bold table is enough.
_ADV = {
    " ": 278, "!": 333, '"': 474, "#": 556, "$": 556, "%": 889, "&": 722,
    "'": 238, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556,
    "7": 556, "8": 556, "9": 556,
    ":": 333, ";": 333, "<": 584, "=": 584, ">": 584, "?": 611, "@": 975,
    "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "[": 333, "\\": 278, "]": 333, "^": 584, "_": 556, "`": 333,
    "a": 556, "b": 611, "c": 556, "d": 611, "e": 556, "f": 333, "g": 611,
    "h": 611, "i": 278, "j": 278, "k": 556, "l": 278, "m": 889, "n": 611,
    "o": 611, "p": 611, "q": 611, "r": 389, "s": 556, "t": 333, "u": 611,
    "v": 556, "w": 778, "x": 556, "y": 556, "z": 500,
    "{": 389, "|": 280, "}": 389, "~": 584,
}
_DEFAULT_ADV = 600


def text_width(text: str, size: float) -> float:
    """Approximate rendered width of `text` at `size` px, in pixels."""
    total = 0
    for ch in str(text):
        total += _ADV.get(ch, _DEFAULT_ADV)
    return total * size / 1000.0


# ---------------------------------------------------------------------------


@dataclass
class LegendItem:
    """One placed legend entry, in composition pixel space."""
    kind: str                 # "swatch" | "circle"
    label: str
    x: float                  # swatch centre / circle centre
    y: float
    label_x: float
    label_y: float
    label_size: float
    color: RGB = (1.0, 1.0, 1.0)
    diameter: float = 20.0
    ctrl_key: str = ""        # MASTER_CONTROLS colour key, when one exists


@dataclass
class LegendLayout:
    items: List[LegendItem] = field(default_factory=list)
    title: str = ""
    title_x: float = 0.0
    title_y: float = 0.0
    rows: int = 1


SWATCH = 20.0          # category swatch is a 20x20 square
LABEL_GAP = 12.0       # swatch/circle edge to its label
BLOCK_GAP = 40.0       # between one entry and the next
GROUP_GAP = 56.0       # between the category group and the size group
ROW_STEP = 46.0        # vertical pitch when the legend wraps


def pack_legend(entries: Sequence[Tuple[str, RGB, str]],
                size_entries: Sequence[Tuple[str, float]],
                size_title: str,
                left: float,
                right: float,
                base_y: float,
                label_size: float,
                size_label_size: float = 18.0) -> LegendLayout:
    """Lay the legend out left to right, wrapping when it runs past `right`.

    `entries` are (label, colour, ctrl_key) category or series swatches.
    `size_entries` are (label, diameter) circles for the size encoding; they
    are kept together as one block so the group never splits across rows.
    """
    out = LegendLayout(title=size_title)
    avail = right - left

    # measure every block first, so we know how many rows we need before we
    # commit to a y for any of them.
    blocks: List[Tuple[str, float, object]] = []
    for label, color, ckey in entries:
        w = SWATCH / 2 + LABEL_GAP + text_width(label, label_size)
        blocks.append(("swatch", w, (label, color, ckey)))

    if size_entries:
        w = 0.0
        for i, (label, diam) in enumerate(size_entries):
            if i:
                w += BLOCK_GAP
            w += diam + LABEL_GAP + text_width(label, size_label_size)
        w = max(w, text_width(size_title, size_label_size))
        blocks.append(("sizegroup", w, list(size_entries)))

    # greedy row assignment
    rows: List[List[Tuple[str, float, object]]] = [[]]
    x = 0.0
    for blk in blocks:
        gap = 0.0 if not rows[-1] else (
            GROUP_GAP if blk[0] == "sizegroup" else BLOCK_GAP)
        if rows[-1] and x + gap + blk[1] > avail:
            rows.append([])
            x = 0.0
            gap = 0.0
        x += gap + blk[1]
        rows[-1].append(blk)
    out.rows = len(rows)

    # place. With N rows the block sits N-1 steps higher so the last row keeps
    # the original baseline.
    for r, row in enumerate(rows):
        y = base_y - (len(rows) - 1 - r) * ROW_STEP
        x = left
        for i, (kind, w, payload) in enumerate(row):
            if i:
                x += GROUP_GAP if kind == "sizegroup" else BLOCK_GAP
            if kind == "swatch":
                label, color, ckey = payload
                out.items.append(LegendItem(
                    kind="swatch", label=label, x=x, y=y,
                    label_x=x + SWATCH / 2 + LABEL_GAP, label_y=y + 7.0,
                    label_size=label_size, color=color, diameter=SWATCH,
                    ctrl_key=ckey))
            else:
                out.title_x = x
                out.title_y = y - 26.0
                cx = x
                for j, (label, diam) in enumerate(payload):
                    if j:
                        cx += BLOCK_GAP + diam / 2.0
                    else:
                        cx += diam / 2.0
                    out.items.append(LegendItem(
                        kind="circle", label=label, x=cx, y=y + 6.0,
                        label_x=cx + diam / 2.0 + LABEL_GAP, label_y=y + 11.0,
                        label_size=size_label_size, diameter=diam))
                    cx += diam / 2.0 + LABEL_GAP + text_width(label, size_label_size)
            x += w
    return out
