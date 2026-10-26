"""
The colour each laser is shown in: roughly what its wavelength looks
like, as the old script showed them (blue, green, red, then darker reds
into the infrared).

No Tk here. Visible wavelengths follow Dan Bruton's well-known
approximation of spectral colours; past 700 nm the eye fades out, so
the colour darkens towards maroon, as the old script's #600000 and
#000000 for 785 and 848 nm did. Those dark ones get a grey ring where
they are drawn, so they still show on the dark theme.
"""

from __future__ import annotations

#: Below this luminance, text on the colour is white.
DARK = 0.18
#: Where infrared colours bottom out: never quite black.
IR_FLOOR = (0x3a, 0x08, 0x08)
#: Deep red reached at 700 nm, from pure red at 645 nm: 652 and 676 nm
#: then look different, as the old script's #FF0000 and #D00000 did.
RED_EDGE = 0xb0


def wavelength_colour(nm: float) -> str:
    """'#rrggbb' for a laser of `nm` nanometres."""
    if nm >= 700:
        # Fade from red at 700 nm to a dark maroon by 850 nm.
        f = min(1.0, (nm - 700) / 150)
        start = (RED_EDGE, 0x00, 0x00)
        rgb = tuple(round(s + (e - s) * f)
                    for s, e in zip(start, IR_FLOOR, strict=True))
        return "#%02x%02x%02x" % rgb
    if nm < 380:
        nm = 380.0
    if nm < 440:
        r, g, b = -(nm - 440) / (440 - 380), 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / (490 - 440), 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, -(nm - 510) / (510 - 490)
    elif nm < 580:
        r, g, b = (nm - 510) / (580 - 510), 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, -(nm - 645) / (645 - 580), 0.0
    else:
        f = (nm - 645) / (700 - 645)
        return "#%02x0000" % round(255 + (RED_EDGE - 255) * f)
    # Dimmer towards the violet end, as the eye sees it.
    k = 0.3 + 0.7 * (nm - 380) / (420 - 380) if nm < 420 else 1.0
    gamma = 0.8
    return "#%02x%02x%02x" % tuple(
        round(255 * (c * k) ** gamma) if c > 0 else 0 for c in (r, g, b)
    )


def luminance(colour: str) -> float:
    """Relative luminance, 0 (black) to 1 (white)."""
    def channel(hex2: str) -> float:
        c = int(hex2, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(colour[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ink_on(colour: str) -> str:
    """Black or white, whichever reads better on `colour`."""
    return "#000000" if luminance(colour) > DARK else "#ffffff"


def needs_ring(colour: str) -> bool:
    return luminance(colour) < 0.05
