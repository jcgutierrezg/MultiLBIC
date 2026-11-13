"""A very small schematic drawing library: SVG out, 10 px grid."""
from html import escape

INK = "#111111"
NET = "#0b5cad"
NOTE = "#555555"
DNP = "#b3261e"
FONT = "Arial, Helvetica, sans-serif"
MONO = "Consolas, 'DejaVu Sans Mono', monospace"


class Sch:
    def __init__(self, w, h, title, sub=""):
        self.w, self.h = w, h
        self.o = []
        self.o.append(
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>')
        self.o.append(
            f'<rect x="8" y="8" width="{w - 16}" height="{h - 16}" '
            f'fill="none" stroke="{INK}" stroke-width="1"/>')
        self.text(24, 36, title, size=18, bold=True)
        if sub:
            self.text(24, 56, sub, size=12, color=NOTE)

    # ---------------------------------------------------------- basics
    def line(self, *pts, color=INK, dash=False, w=1.6):
        d = " ".join(f"{x},{y}" for x, y in pts)
        da = ' stroke-dasharray="5,4"' if dash else ""
        self.o.append(
            f'<polyline points="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{w}" stroke-linecap="round" '
            f'stroke-linejoin="round"{da}/>')

    def rect(self, x, y, w, h, color=INK, dash=False, fill="#ffffff", sw=1.6):
        da = ' stroke-dasharray="5,4"' if dash else ""
        self.o.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
            f'stroke="{color}" stroke-width="{sw}"{da}/>')

    def dot(self, x, y):
        self.o.append(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{INK}"/>')

    def text(self, x, y, t, anchor="start", size=12, bold=False, color=INK,
             mono=False, italic=False):
        fw = ' font-weight="bold"' if bold else ""
        fs = ' font-style="italic"' if italic else ""
        ff = MONO if mono else FONT
        self.o.append(
            f'<text x="{x}" y="{y}" font-family="{ff}" font-size="{size}" '
            f'text-anchor="{anchor}" fill="{color}"{fw}{fs}>{escape(t)}</text>')

    def note(self, x, y, lines, size=12, color=NOTE, lh=16):
        for i, t in enumerate(lines):
            self.text(x, y + i * lh, t, size=size, color=color)

    def refval(self, x, y, ref, val, anchor="start", dnp=False):
        c = DNP if dnp else INK
        self.text(x, y, ref, anchor=anchor, size=12, bold=True, color=c)
        if val:
            self.text(x, y + 14, val, anchor=anchor, size=11, color=c)

    # ------------------------------------------------------ net labels
    def label(self, x, y, name, side="r"):
        """A net label at the open end of a wire. side: where the text goes."""
        if side == "r":
            self.line((x, y), (x + 8, y), color=NET)
            self.text(x + 12, y + 4, name, size=12, color=NET, mono=True,
                      bold=True)
        elif side == "l":
            self.line((x, y), (x - 8, y), color=NET)
            self.text(x - 12, y + 4, name, anchor="end", size=12, color=NET,
                      mono=True, bold=True)
        elif side == "u":
            self.line((x, y), (x, y - 8), color=NET)
            self.text(x, y - 13, name, anchor="middle", size=12, color=NET,
                      mono=True, bold=True)
        elif side == "d":
            self.line((x, y), (x, y + 8), color=NET)
            self.text(x, y + 22, name, anchor="middle", size=12, color=NET,
                      mono=True, bold=True)

    def netname(self, x, y, name, anchor="middle"):
        self.text(x, y, name, anchor=anchor, size=11, color=NET, mono=True)

    def gnd(self, x, y):
        self.line((x - 10, y), (x + 10, y))
        self.line((x - 6, y + 4), (x + 6, y + 4))
        self.line((x - 2, y + 8), (x + 2, y + 8))

    def pwr(self, x, y, name):
        self.line((x, y), (x, y - 12))
        self.line((x - 9, y - 12), (x + 9, y - 12), w=2.2)
        self.text(x, y - 17, name, anchor="middle", size=12, color=NET,
                  mono=True, bold=True)

    def tp(self, x, y, ref, side="u"):
        self.o.append(
            f'<circle cx="{x}" cy="{y}" r="4.5" fill="#ffffff" '
            f'stroke="{INK}" stroke-width="1.6"/>')
        if side == "u":
            self.text(x, y - 9, ref, anchor="middle", size=10, color=NOTE)
        else:
            self.text(x, y + 18, ref, anchor="middle", size=10, color=NOTE)

    def nc(self, x, y):
        self.line((x - 4, y - 4), (x + 4, y + 4), w=1.3)
        self.line((x - 4, y + 4), (x + 4, y - 4), w=1.3)

    # ------------------------------------------------------- passives
    def res_h(self, x, y, ref, val, dnp=False):
        c = DNP if dnp else INK
        self.line((x, y), (x + 10, y), color=c)
        self.rect(x + 10, y - 7, 40, 14, color=c, dash=dnp)
        self.line((x + 50, y), (x + 60, y), color=c)
        self.text(x + 30, y - 12, ref, anchor="middle", bold=True, color=c)
        self.text(x + 30, y + 21, val, anchor="middle", size=11, color=c)

    def res_v(self, x, y, ref, val, side="r", dnp=False):
        c = DNP if dnp else INK
        self.line((x, y), (x, y + 10), color=c)
        self.rect(x - 7, y + 10, 14, 40, color=c, dash=dnp)
        self.line((x, y + 50), (x, y + 60), color=c)
        if side == "r":
            self.refval(x + 12, y + 27, ref, val, dnp=dnp)
        else:
            self.refval(x - 12, y + 27, ref, val, anchor="end", dnp=dnp)

    def cap_v(self, x, y, ref, val, side="r", dnp=False, length=60,
              polar=False):
        c = DNP if dnp else INK
        m = y + length // 2
        self.line((x, y), (x, m - 4), color=c, dash=dnp)
        self.line((x - 12, m - 4), (x + 12, m - 4), color=c, w=2.2)
        self.line((x - 12, m + 4), (x + 12, m + 4), color=c, w=2.2)
        self.line((x, m + 4), (x, y + length), color=c, dash=dnp)
        if polar:
            self.text(x - 16, m - 8, "+", anchor="middle", size=12, color=c)
        if side == "r":
            self.refval(x + 17, m - 2, ref, val, dnp=dnp)
        else:
            self.refval(x - 17, m - 2, ref, val, anchor="end", dnp=dnp)

    def cap_h(self, x, y, ref, val):
        self.line((x, y), (x + 16, y))
        self.line((x + 16, y - 12), (x + 16, y + 12), w=2.2)
        self.line((x + 24, y - 12), (x + 24, y + 12), w=2.2)
        self.line((x + 24, y), (x + 40, y))
        self.text(x + 20, y - 17, ref, anchor="middle", bold=True)
        self.text(x + 20, y + 26, val, anchor="middle", size=11)

    def fuse_h(self, x, y, ref, val):
        self.line((x, y), (x + 10, y))
        self.rect(x + 10, y - 7, 40, 14)
        self.line((x + 10, y), (x + 50, y), w=1.2)
        self.line((x + 50, y), (x + 60, y))
        self.text(x + 30, y - 12, ref, anchor="middle", bold=True)
        self.text(x + 30, y + 21, val, anchor="middle", size=11)

    def diode_v(self, x, y, ref, val, length=120, side="l", dnp=False,
                pins=("K", "A")):
        """Cathode at the top (x, y), anode at the bottom."""
        c = DNP if dnp else INK
        m = y + length // 2
        self.line((x, y), (x, m - 10), color=c, dash=dnp)
        self.o.append(
            f'<polygon points="{x - 10},{m + 10} {x + 10},{m + 10} '
            f'{x},{m - 10}" fill="#ffffff" stroke="{c}" stroke-width="1.6"/>')
        # Schottky bar
        self.line((x - 14, m - 6), (x - 10, m - 6), (x - 10, m - 10),
                  (x + 10, m - 10), (x + 10, m - 14), (x + 14, m - 14),
                  color=c)
        self.line((x, m + 10), (x, y + length), color=c, dash=dnp)
        self.text(x + 5, m - 16, pins[0], size=9, color=NOTE)
        self.text(x + 5, m + 22, pins[1], size=9, color=NOTE)
        if side == "l":
            self.refval(x - 18, m - 2, ref, val, anchor="end", dnp=dnp)
        else:
            self.refval(x + 18, m - 2, ref, val, dnp=dnp)

    # --------------------------------------------------------- actives
    def nmos(self, gx, gy, ref, val, side="r"):
        """Gate pin at (gx, gy); drain at (gx+40, gy-30); source (gx+40, gy+30).
        SOT-23 pin numbers: 1 gate, 2 source, 3 drain."""
        self.line((gx, gy), (gx + 22, gy))
        self.line((gx + 22, gy - 13), (gx + 22, gy + 13), w=2.0)
        self.line((gx + 28, gy - 16), (gx + 28, gy + 16), w=2.0)
        self.line((gx + 28, gy - 10), (gx + 40, gy - 10), (gx + 40, gy - 30))
        self.line((gx + 28, gy + 10), (gx + 40, gy + 10), (gx + 40, gy + 30))
        # arrow on the source, pointing out (N-channel)
        self.o.append(
            f'<polygon points="{gx + 39},{gy + 10} {gx + 32},{gy + 6} '
            f'{gx + 32},{gy + 14}" fill="{INK}"/>')
        self.text(gx + 6, gy - 4, "1", size=9, color=NOTE)
        self.text(gx + 44, gy - 20, "3", size=9, color=NOTE)
        self.text(gx + 44, gy + 28, "2", size=9, color=NOTE)
        self.text(gx + 14, gy + 14, "G", size=9, color=NOTE, anchor="end")
        self.text(gx + 30, gy - 20, "D", size=9, color=NOTE, anchor="end")
        self.text(gx + 30, gy + 28, "S", size=9, color=NOTE, anchor="end")
        if side == "r":
            self.refval(gx + 54, gy - 2, ref, val)
        else:
            self.refval(gx - 6, gy + 30, ref, val, anchor="end")

    def opamp(self, x, y, ref, pins=("3", "2", "1"), val=""):
        """IN+ at (x, y), IN- at (x, y+40), OUT at (x+80, y+20)."""
        self.o.append(
            f'<polygon points="{x + 10},{y - 18} {x + 10},{y + 58} '
            f'{x + 70},{y + 20}" fill="#ffffff" stroke="{INK}" '
            f'stroke-width="1.6"/>')
        self.line((x, y), (x + 10, y))
        self.line((x, y + 40), (x + 10, y + 40))
        self.line((x + 70, y + 20), (x + 80, y + 20))
        self.text(x + 15, y + 5, "+", size=13)
        self.text(x + 15, y + 45, "−", size=13)
        self.text(x + 7, y - 4, pins[0], size=9, color=NOTE, anchor="end")
        self.text(x + 7, y + 36, pins[1], size=9, color=NOTE, anchor="end")
        self.text(x + 73, y + 15, pins[2], size=9, color=NOTE)
        self.text(x + 44, y - 12, ref, bold=True)
        if val:
            self.text(x + 44, y + 60, val, size=11)

    def conn(self, x, y, ref, desc, pins, w=110, pitch=40):
        """Pins on the left edge. pins: list of (number, name)."""
        h = pitch * len(pins)
        self.rect(x, y, w, h)
        pts = []
        for i, (num, name) in enumerate(pins):
            py = y + pitch // 2 + i * pitch
            self.line((x - 20, py), (x, py))
            self.text(x - 8, py - 4, str(num), size=9, color=NOTE,
                      anchor="middle")
            self.text(x + 6, py + 4, name, size=11)
            pts.append((x - 20, py))
        self.text(x, y - 20, ref, bold=True)
        self.text(x, y - 6, desc, size=11)
        return pts

    def ic(self, x, y, w, ref, name, left, right, pitch=24, stub=20,
           labels=True):
        """left/right: lists of (number, pin name, net or None, or 'nc').
        Returns {number: (x, y)} of each pin's outer end."""
        n = max(len(left), len(right))
        h = pitch * n + 12
        self.rect(x, y, w, h)
        self.text(x, y - 20, ref, bold=True, size=13)
        self.text(x, y - 6, name, size=11)
        pos = {}
        for i, p in enumerate(left):
            if p is None:
                continue
            num, pn, net = p
            py = y + 18 + i * pitch
            self.line((x - stub, py), (x, py))
            self.text(x - 4, py - 4, str(num), size=9, color=NOTE,
                      anchor="end")
            self.text(x + 6, py + 4, pn, size=11)
            pos[num] = (x - stub, py)
            if net == "nc":
                self.nc(x - stub, py)
            elif net and labels:
                self.text(x - stub - 6, py + 4, net, anchor="end", size=12,
                          color=NET, mono=True, bold=True)
        for i, p in enumerate(right):
            if p is None:
                continue
            num, pn, net = p
            py = y + 18 + i * pitch
            self.line((x + w, py), (x + w + stub, py))
            self.text(x + w + 4, py - 4, str(num), size=9, color=NOTE)
            self.text(x + w - 6, py + 4, pn, size=11, anchor="end")
            pos[num] = (x + w + stub, py)
            if net == "nc":
                self.nc(x + w + stub, py)
            elif net and labels:
                self.text(x + w + stub + 6, py + 4, net, size=12, color=NET,
                          mono=True, bold=True)
        return pos

    def table(self, x, y, cols, rows, widths, size=11, rh=18):
        cx = x
        for c, wdt in zip(cols, widths, strict=True):
            self.text(cx, y, c, size=size, bold=True)
            cx += wdt
        self.line((x, y + 5), (x + sum(widths), y + 5), w=1.0)
        for r, row in enumerate(rows):
            cx = x
            for c, wdt in zip(row, widths, strict=True):
                self.text(cx, y + (r + 1) * rh + 2, c, size=size)
                cx += wdt

    def save(self, path):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}">\n'
            + "\n".join(self.o) + "\n</svg>\n")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
