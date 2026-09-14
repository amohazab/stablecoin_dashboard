"""B-11a″: the in-house SVG writer (P-7.01 R5; R-B11.3, R-B11.11). No plotting library.

Pure string builders with deterministic geometry: every coordinate is rounded
half-up to 0.1 px, so the same inputs give byte-identical SVG (rubric 0.3).
Geometry is computed from numeric values; every TEXT label, axis ticks included,
arrives pre-formatted by the page's `fmt` filter (DET-89's single owner) - this
module formats no figure. Every figure is `viewBox` + `width="100%"`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from html import escape

ACCENT = "#1f5fa8"
MUTED = "#6b7886"
RULE = "#d9dee4"
INK = "#1b2430"
WARN = "#b07a2a"
# one colour per verifiability class (R-B11.11): on-chain / one layer down / disclosures
CLASS_FILLS = ("#1f5fa8", "#5f9ad6", "#c7a35a")


def _r(x) -> str:
    """0.1 px, half-up, no trailing `.0`."""
    v = Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    s = format(v, "f")
    return s[:-2] if s.endswith(".0") else s


def _text(x, y, s, anchor="start", size=13, fill=INK, weight="normal") -> str:
    return (f'<text x="{_r(x)}" y="{_r(y)}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill}" font-weight="{weight}">{escape(s)}</text>')


def _rect(x, y, w, h, fill, rx=0, extra="") -> str:
    r = f' rx="{rx}"' if rx else ""
    return (f'<rect x="{_r(x)}" y="{_r(y)}" width="{_r(max(Decimal(str(w)), Decimal(0)))}" '
            f'height="{_r(h)}" fill="{fill}"{r}{extra}/>')


def _svg(w, h, body: list[str], title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_r(w)} {_r(h)}" '
            f'width="100%" role="img" aria-label="{escape(title)}" '
            f'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif">'
            f"<title>{escape(title)}</title>" + "".join(body) + "</svg>")


def tree_diagram(root_lines: list[str], side_note: str | None,
                 bars: list[tuple[str, Decimal, str]],
                 columns: list[list[tuple[str, str, str | None]]], caption: str,
                 per_column: int = 6) -> str:
    """R-B11.3 / R-B11.11: root box above; the three bars as one horizontal
    stacked band, a colour per class, with a legend; node boxes beneath each bar
    (symbol, share, staleness pill); the side note beside the root, outside the
    band (GHO's off-mainnet line). `bars` = [(label, share, share_label)];
    `columns[i]` = [(symbol, share_label, pill)] for bar i."""
    w, x0 = 1000, 20
    bw = w - 2 * x0
    body = []
    rw, rh = 420, 26 + 20 * (len(root_lines) - 1) + 14
    rx = (w - rw) / 2 if side_note is None else x0
    body.append(_rect(rx, 10, rw, rh, "#ffffff", rx=10,
                      extra=f' stroke="{ACCENT}" stroke-width="1.5"'))
    for i, line in enumerate(root_lines):
        body.append(_text(rx + rw / 2, 34 + 20 * i, line, anchor="middle",
                          size=16 if i == 0 else 13, weight="600" if i == 0 else "normal"))
    if side_note:
        sx = rx + rw + 40
        body.append(_rect(sx, 10, w - x0 - sx, rh, "#fbf4ea", rx=10,
                          extra=f' stroke="{WARN}" stroke-dasharray="6 4"'))
        body.append(f'<line x1="{_r(rx + rw)}" y1="{_r(10 + rh / 2)}" x2="{_r(sx)}" '
                    f'y2="{_r(10 + rh / 2)}" stroke="{WARN}" stroke-dasharray="6 4"/>')
        body.append(_text(sx + (w - x0 - sx) / 2, 10 + rh / 2 + 5, side_note, anchor="middle",
                          size=13, fill="#7a5418"))
    band_y = 10 + rh + 30
    body.append(f'<line x1="{_r(rx + rw / 2)}" y1="{_r(10 + rh)}" x2="{_r(rx + rw / 2)}" '
                f'y2="{_r(band_y)}" stroke="{MUTED}"/>')
    x = Decimal(x0)
    for i, (_label, share, _lab) in enumerate(bars):
        seg = Decimal(bw) * Decimal(share)
        body.append(_rect(x, band_y, seg, 36, CLASS_FILLS[i % 3]))
        x += seg
    ly = band_y + 60
    colw = Decimal(bw) / max(len(bars), 1)
    for i, (label, _share, lab) in enumerate(bars):
        cx = x0 + colw * i
        body.append(_rect(cx, ly - 12, 14, 14, CLASS_FILLS[i % 3], rx=3))
        body.append(_text(cx + 22, ly, f"{label} — {lab}", size=14, weight="600"))
        items = columns[i] if i < len(columns) else []
        for j, (sym, sl, pill) in enumerate(items[:per_column]):
            by = ly + 16 + 38 * j
            body.append(_rect(cx, by, colw - 16, 30, "#f5f7fa", rx=6,
                              extra=f' stroke="{RULE}"'))
            body.append(_text(cx + 10, by + 20, sym, size=13, weight="600"))
            share_x = cx + colw - 26 - (88 if pill else 0)
            body.append(_text(share_x, by + 20, sl, anchor="end", size=13))
            if pill:
                body.append(_rect(cx + colw - 106, by + 7, 80, 17, "#ffffff", rx=8,
                                  extra=f' stroke="{RULE}"'))
                body.append(_text(cx + colw - 66, by + 20, pill, anchor="middle", size=11,
                                  fill=MUTED))
        if len(items) > per_column:
            body.append(_text(cx + 10, ly + 16 + 38 * per_column + 14,
                              f"+{len(items) - per_column} more below", size=12, fill=MUTED))
    h = ly + 16 + 38 * per_column + 34
    body.append(_text(x0, h - 6, caption, size=13, fill=MUTED))
    return _svg(w, h, body, "verifiability tree")


def _axes(left, top, pw, ph, y_ticks: list[tuple[Decimal, str]], ymax: Decimal,
          y_title: str) -> list[str]:
    out = [f'<line x1="{left}" y1="{top + ph}" x2="{left + pw}" y2="{top + ph}" '
           f'stroke="{MUTED}"/>',
           f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + ph}" stroke="{MUTED}"/>']
    for val, lab in y_ticks:
        y = top + ph - Decimal(ph) * Decimal(val) / ymax
        out.append(f'<line x1="{left - 5}" y1="{_r(y)}" x2="{left + pw}" y2="{_r(y)}" '
                   f'stroke="{RULE}"/>')
        out.append(_text(left - 8, y + 4, lab, anchor="end", size=12, fill=MUTED))
    out.append(_text(left, top - 12, y_title, size=12, fill=MUTED))
    return out


def line_chart(points: list[tuple[str, Decimal, str]], title: str, x_title: str,
               y_title: str, y_ticks: list[tuple[Decimal, str]]) -> str:
    """Chart A: one line, equal x steps, $-labelled y axis from `y_ticks`."""
    w, h, left, top, pw, ph = 1000, 320, 90, 56, 870, 200
    ymax = max([Decimal(p[1]) for p in points] + [Decimal(t[0]) for t in y_ticks]) or Decimal(1)
    body = [_text(20, 22, title, size=15, weight="600")]
    body += _axes(left, top, pw, ph, y_ticks, ymax, y_title)
    step = Decimal(pw - 40) / max(len(points) - 1, 1)
    coords = []
    for i, (xl, yv, yl) in enumerate(points):
        cx = left + 20 + step * i
        cy = top + ph - Decimal(ph) * Decimal(yv) / ymax
        coords.append(f"{_r(cx)},{_r(cy)}")
        body.append(f'<circle cx="{_r(cx)}" cy="{_r(cy)}" r="5" fill="{ACCENT}"/>')
        body.append(_text(cx, top + ph + 22, xl, anchor="middle", size=13))
        body.append(_text(cx, cy - 12, yl, anchor="middle", size=12))
    body.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{ACCENT}" '
                'stroke-width="2.5"/>')
    body.append(_text(left + pw / 2, h - 10, x_title, anchor="middle", size=12, fill=MUTED))
    return _svg(w, h, body, title)


def stacked_columns(points: list[tuple[str, Decimal, Decimal, str]], title: str,
                    legend: tuple[str, str], x_title: str, y_title: str,
                    y_ticks: list[tuple[Decimal, str]]) -> str:
    """Chart B: four columns, pool depth with any GSM contribution stacked on
    top; $-labelled y axis. `points` = [(x_label, pool, gsm, total_label)]."""
    w, h, left, top, pw, ph = 1000, 340, 90, 56, 870, 200
    ymax = max([Decimal(p[1]) + Decimal(p[2]) for p in points]
               + [Decimal(t[0]) for t in y_ticks]) or Decimal(1)
    colw = Decimal(pw) / (len(points) * 2)
    body = [_text(20, 22, title, size=15, weight="600")]
    body += _axes(left, top, pw, ph, y_ticks, ymax, y_title)
    for i, (xl, pool, gsm, tl) in enumerate(points):
        x = left + colw * (2 * i) + colw / 2
        hp = Decimal(ph) * Decimal(pool) / ymax
        hg = Decimal(ph) * Decimal(gsm) / ymax
        body.append(_rect(x, top + ph - hp, colw, hp, ACCENT))
        if Decimal(gsm) > 0:
            body.append(_rect(x, top + ph - hp - hg, colw, hg, WARN))
        body.append(_text(x + colw / 2, top + ph + 22, xl, anchor="middle", size=13))
        body.append(_text(x + colw / 2, top + ph - hp - hg - 8, tl, anchor="middle", size=12))
    body.append(_text(left + pw / 2, top + ph + 44, x_title, anchor="middle", size=12,
                      fill=MUTED))
    body.append(_rect(left, h - 24, 12, 12, ACCENT))
    body.append(_text(left + 18, h - 14, legend[0], size=12))
    if any(Decimal(p[2]) > 0 for p in points):
        body.append(_rect(left + 220, h - 24, 12, 12, WARN))
        body.append(_text(left + 238, h - 14, legend[1], size=12))
    return _svg(w, h, body, title)


def two_bars(a: tuple[str, Decimal, str], b: tuple[str, Decimal, str], title: str) -> str:
    """The GHO Member-2 collapse: two bars on ONE linear axis, so the sliver is
    the finding (inventory §I.4). Each = (caption, value, value_label)."""
    w, left, bw = 1000, 20, 780
    vmax = max(Decimal(a[1]), Decimal(b[1])) or Decimal(1)
    body = [_text(left, 22, title, size=15, weight="600")]
    for i, (cap, v, lab) in enumerate((a, b)):
        y = 50 + 52 * i
        body.append(_text(left, y, cap, size=13))
        body.append(_rect(left, y + 8, Decimal(bw) * Decimal(v) / vmax, 22,
                          ACCENT if i == 0 else WARN))
        body.append(_text(left + Decimal(bw) * Decimal(v) / vmax + 10, y + 25, lab, size=13,
                          weight="600"))
    return _svg(w, 160, body, title)
