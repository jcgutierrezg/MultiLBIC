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
        theme._multilbic = True  # type: ignore[attr-defined]
        theme.set_accent(ACCENT_KEY)
        theme.on_change(_extra_styles)
    if mode is not None:
        # Not saved: a test asking for a mode must not change the
        # operator's choice.
        theme.set_mode(mode, save=False)
    return theme


def _extra_styles(theme: Theme) -> None:
    p, accent = theme.palette, theme.accent
    style = theme.style
    # A laser that is on: filled with the accent, so it reads at a
    # glance across the room.
    lit_hover = blend(accent, p.ink, 0.12)
    style.configure("Lit.TButton", background=accent,
                    foreground=p.on_accent, bordercolor=accent,
                    lightcolor=accent, darkcolor=accent, font="SMUBold")
    style.map("Lit.TButton",
              background=[("disabled", p.bg), ("active", lit_hover)],
              foreground=[("disabled", p.muted)],
              lightcolor=[("active", lit_hover)],
              darkcolor=[("active", lit_hover)])
    # The jog pad: a ring in the accent while it has the keys.
    style.configure("Keys.TFrame", background=p.bg, borderwidth=2,
                    relief="solid", bordercolor=p.rule)
    style.configure("KeysOn.TFrame", background=p.bg, borderwidth=2,
                    relief="solid", bordercolor=accent)
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


def section(parent: tk.Misc, title: str) -> ttk.LabelFrame:
    return ttk.LabelFrame(parent, text=title, padding=(10, 6))
