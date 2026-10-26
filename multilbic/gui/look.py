"""
MultiLBIC's look on top of SMUniversal's theme (`core/gui/theme.py`):
the same two modes, safety colours and fonts, with an accent of its own
and the few styles SMUniversal has no use for.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from smuniversal_lab_suite.core.gui import theme as smu_theme
from smuniversal_lab_suite.core.gui.theme import Theme, blend

ACCENT_KEY = "multilbic"
#: Teal: not the red of Stop and faults, not the green of "connected",
#: and not any SMUniversal experiment's colour.
ACCENT = {smu_theme.LIGHT: "#00707c", smu_theme.DARK: "#3cc6d3"}


def make_theme(root: tk.Misc, mode: str | None = None) -> Theme:
    """The theme of `root`'s Tk, with MultiLBIC's accent and styles.
    One per Tk: a second would re-create the named fonts, which Tk
    refuses, so a Tk that has one gets it back."""
    smu_theme.ACCENTS.setdefault(ACCENT_KEY, ACCENT)
    theme = smu_theme.theme_for(root)
    if not getattr(theme, "_multilbic", False):
        theme._multilbic = True
        theme.set_accent(ACCENT_KEY)
        theme.on_change(_extra_styles)
    if mode is not None:
        # Not saved: a test asking for a mode must not change the
        # operator's choice.
        theme.set_mode(mode, save=False)
    return theme


def _extra_styles(theme: Theme) -> None:
    """The styles SMUniversal has no use for. A lit laser's button is
    styled per laser, in its own colour (`laser_styles`)."""
    p, accent = theme.palette, theme.accent
    style = theme.style
    # The jog pad: a ring in the accent while it has the keys.
    style.configure("Keys.TFrame", background=p.bg, borderwidth=2,
                    relief="solid", bordercolor=p.rule)
    style.configure("KeysOn.TFrame", background=p.bg, borderwidth=2,
                    relief="solid", bordercolor=accent)
    # SMUniversal's theme paints a disabled box plain before it asks
    # whether it is ticked, so a ticked box looks empty while a run has
    # the form locked. Ticked and disabled: a grey tick.
    soft = blend(accent, p.field, 0.72)
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.map(widget,
                  indicatorbackground=[("disabled", "selected", p.muted),
                                       ("disabled", p.bg),
                                       ("selected", accent),
                                       ("pressed", soft)],
                  indicatorforeground=[("disabled", "selected", p.bg),
                                       ("selected", p.on_accent)],
                  upperbordercolor=[("disabled", "selected", p.muted),
                                    ("selected", accent)],
                  lowerbordercolor=[("disabled", "selected", p.muted),
                                    ("selected", accent)])
    style.configure("Big.Stop.TButton", font="SMUCardTitle",
                    padding=(22, 8))
    style.configure("Position.TLabel", font="SMUCardTitle")


def amps(value: float | None) -> str:
    """'12.34 nA', '1.203 uA', '-' for nothing."""
    if value is None or not math.isfinite(value):
        return "-"
    for unit, scale in (("mA", 1e-3), ("uA", 1e-6), ("nA", 1e-9)):
        if abs(value) >= scale:
            return f"{value / scale:.4g} {unit}"
    return f"{value / 1e-12:.3g} pA"


def lamp(parent: tk.Misc, theme: Theme, size: int = 12) -> tk.Canvas:
    """A round status lamp; `set_lamp` colours it."""
    canvas = tk.Canvas(parent, width=size, height=size,
                       highlightthickness=0, borderwidth=0)
    canvas.create_oval(1, 1, size - 1, size - 1, outline="", tags="lamp")
    canvas._lamp_state = "off"  # type: ignore[attr-defined]

    def repaint(t: Theme) -> None:
        canvas.configure(background=t.palette.bg)
        set_lamp(canvas, t, canvas._lamp_state)  # type: ignore[attr-defined]

    theme.on_change(repaint, widget=canvas)
    return canvas


def set_lamp(canvas: tk.Canvas, theme: Theme, state: str) -> None:
    """'good', 'bad' or 'off'."""
    canvas._lamp_state = state  # type: ignore[attr-defined]
    p = theme.palette
    colour = {"good": p.good, "bad": p.bad}.get(state, p.muted)
    canvas.itemconfigure("lamp", fill=colour)


def blend_soft(theme: Theme) -> str:
    """The accent faded into the field colour: a filled shape that
    doesn't shout."""
    return blend(theme.accent, theme.palette.field, 0.8)


def section(parent: tk.Misc, title: str) -> ttk.LabelFrame:
    return ttk.LabelFrame(parent, text=title, padding=(10, 6))


# ---- laser colours ----

#: The ring round a swatch too dark to see on the dark theme.
RING = "#8a8a8a"
_SWATCHES: dict[tuple[str, str, int], tk.PhotoImage] = {}


def swatch(master: tk.Misc, colour: str, size: int = 14) -> tk.PhotoImage:
    """A round dot of `colour`, for a button, a box or a tab. Kept here
    once made: Tk forgets an image Python no longer holds."""
    from multilbic.gui.spectrum import needs_ring

    key = (str(master.winfo_toplevel()), colour, size)
    image = _SWATCHES.get(key)
    if image is not None:
        return image
    image = tk.PhotoImage(master=master, width=size, height=size)
    ring = needs_ring(colour)
    r = size / 2 - 0.5
    for y in range(size):
        dy = y + 0.5 - size / 2
        span = (r * r - dy * dy) ** 0.5 if abs(dy) <= r else -1.0
        if span < 0:
            continue
        x0, x1 = round(size / 2 - span), round(size / 2 + span)
        if x1 <= x0:
            continue
        image.put(colour, to=(x0, y, x1, y + 1))
        if ring:
            image.put(RING, to=(x0, y, x0 + 1, y + 1))
            image.put(RING, to=(x1 - 1, y, x1, y + 1))
            if abs(dy) > r - 1.2:
                image.put(RING, to=(x0, y, x1, y + 1))
    _SWATCHES[key] = image
    return image


def laser_styles(theme: Theme, lasers: dict[int, str]) -> None:
    """`Laser<n>.Lit.TButton` for each laser: the button filled with the
    laser's colour while it is on, softer while a run locks it."""
    from multilbic.gui.spectrum import ink_on

    p = theme.palette
    style = theme.style
    for number, colour in lasers.items():
        name = f"Laser{number}.Lit.TButton"
        hover = blend(colour, p.ink, 0.15)
        locked = blend(colour, p.bg, 0.35)
        ink = ink_on(colour)
        style.configure(name, background=colour, foreground=ink,
                        bordercolor=colour, lightcolor=colour,
                        darkcolor=colour, font="SMUBold")
        style.map(name,
                  background=[("disabled", locked), ("active", hover)],
                  foreground=[("disabled", ink_on(locked))],
                  lightcolor=[("disabled", locked), ("active", hover)],
                  darkcolor=[("disabled", locked), ("active", hover)])


# ---- the emblem ----

EMBLEM_SIZE = 44


def draw_emblem(canvas: tk.Canvas, theme: Theme,
                lasers: list[tuple[int, str]]) -> None:
    """MultiLBIC's emblem: the laser revolver seen from below, a ring in
    the accent with each laser's colour at its place - two groups of
    three on opposite sides, as the servo turns them - and the beam's
    spot in the middle. Drawn, so it follows the theme."""
    from multilbic.gui.spectrum import needs_ring

    canvas.delete("all")
    canvas.configure(background=theme.palette.header)
    size = int(canvas.cget("width"))
    c, ring = size / 2, size * 0.36
    canvas.create_oval(c - ring, c - ring, c + ring, c + ring,
                       outline=theme.accent, width=2)
    # Lasers 1-3 across the top, 4-6 across the bottom.
    angles = (150, 90, 30, 210, 270, 330)
    dot = size * 0.1
    for (_, colour), angle in zip(lasers, angles, strict=False):
        x = c + ring * math.cos(math.radians(angle))
        y = c - ring * math.sin(math.radians(angle))
        canvas.create_oval(x - dot, y - dot, x + dot, y + dot, fill=colour,
                           outline=RING if needs_ring(colour) else colour)
    spot = size * 0.06
    canvas.create_oval(c - spot, c - spot, c + spot, c + spot,
                       fill=theme.accent, outline="")
