"""
Single key presses from the terminal, for jogging during calibration.

On Windows `msvcrt` reads keys directly. Elsewhere (the Pi, an SSH
session) the terminal is put in cbreak mode for the duration: keys
arrive one at a time without Enter, and Ctrl+C still works. Either way
the terminal is put back as it was on the way out.

`flush()` throws away keys pressed while the stage was moving, so
holding a key down jogs step by step instead of queueing up moves that
carry on after it is released.

Arrow and function keys arrive as escape sequences. They are swallowed
whole, so they neither jog nor end key mode; a lone Esc ends it.

The `sys.platform` checks are what let mypy skip, on each platform, the
modules that only exist on the other.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import Protocol

ESCAPE = "\x1b"
CTRL_C = "\x03"
#: msvcrt's prefix for arrow and function keys; a second code follows.
_WINDOWS_PREFIXES = ("\x00", "\xe0")


class KeySource(Protocol):
    def read(self) -> str:
        """The next key: one character, `ESCAPE` for Esc, `""` for a key
        that is ignored (arrows and the like)."""
        ...

    def flush(self) -> None:
        """Drop keys already pressed but not read."""
        ...


class _WindowsKeys:
    def read(self) -> str:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        import msvcrt

        key = msvcrt.getwch()
        if key in _WINDOWS_PREFIXES:
            msvcrt.getwch()
            return ""
        return key

    def flush(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()


class _PosixKeys:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def _ready(self, timeout: float) -> bool:
        import select

        return bool(select.select([self._fd], [], [], timeout)[0])

    def read(self) -> str:
        key = os.read(self._fd, 1).decode(errors="replace")
        if key == ESCAPE and self._ready(0.05):
            # An escape sequence (arrow keys, ...): drain and ignore it.
            while self._ready(0.01):
                os.read(self._fd, 16)
            return ""
        return key

    def flush(self) -> None:
        if sys.platform == "win32":
            raise RuntimeError("POSIX only")
        import termios

        termios.tcflush(self._fd, termios.TCIFLUSH)


@contextlib.contextmanager
def terminal_keys() -> Iterator[KeySource]:
    """Key presses from this process's terminal."""
    if sys.platform == "win32":
        yield _WindowsKeys()
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            raise RuntimeError("key mode needs a terminal")
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            yield _PosixKeys(fd)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
