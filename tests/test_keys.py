"""The terminal key reader the Pi uses, through a pseudo-terminal."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the POSIX reader; Windows uses msvcrt"
)


def test_keys_escape_sequences_and_flush():
    import pty

    from multilbic.run.keys import ESCAPE, _PosixKeys

    master, slave = pty.openpty()
    try:
        import tty

        tty.setcbreak(slave)
        keys = _PosixKeys(slave)
        os.write(master, b"w")
        assert keys.read() == "w"
        # An arrow key is one escape sequence: swallowed whole.
        os.write(master, b"\x1b[A")
        assert keys.read() == ""
        # A lone Esc comes through.
        os.write(master, b"\x1b")
        assert keys.read() == ESCAPE
        # Keys typed during a move are dropped by flush().
        os.write(master, b"ddd")
        keys.flush()
        os.write(master, b"q")
        assert keys.read() == "q"
    finally:
        os.close(master)
        os.close(slave)
