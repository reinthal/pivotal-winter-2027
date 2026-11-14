#!/usr/bin/env python3
"""Countdown timer with a big full-terminal display.

Usage:
  timer.py 25        25 minutes (a bare number is minutes)
  timer.py 90s       90 seconds
  timer.py 1h5m30s   any combination of h / m / s
  timer.py 12:30     mm:ss (or h:mm:ss)

Keys:
  space  pause / resume
  r      restart
  q      quit (Ctrl-C also works)

The digits scale to fill the terminal. When time is up the display flashes
and the terminal bell rings until a key is pressed.
"""

import math
import os
import re
import select
import shutil
import sys
import termios
import time
import tty

TICK_SECONDS = 0.1
FLASH_SECONDS = 0.5
PIXEL_ROWS = 5

FONT = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    ":": ["0", "1", "0", "1", "0"],
}


def parse_duration(text: str) -> int:
    """Return the duration in whole seconds."""
    if re.fullmatch(r"\d+", text):
        seconds = int(text) * 60
    elif re.fullmatch(r"\d+(:\d{1,2}){1,2}", text):
        seconds = 0
        for part in text.split(":"):
            seconds = seconds * 60 + int(part)
    elif text and (m := re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)):
        hours, minutes, secs = (int(g or 0) for g in m.groups())
        seconds = hours * 3600 + minutes * 60 + secs
    else:
        raise SystemExit(
            f"timer: cannot parse duration {text!r} (try 25, 90s, 1h5m, 12:30)"
        )
    if seconds == 0:
        raise SystemExit("timer: duration must be greater than zero")
    return seconds


def clock_text(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def big_lines(text: str, scale: int) -> list[str]:
    """Render text as block characters; one font pixel is 2*scale wide, scale tall."""
    lines = []
    for row in range(PIXEL_ROWS):
        pixels = "0".join(FONT[ch][row] for ch in text)
        line = "".join(("█" if p == "1" else " ") * 2 * scale for p in pixels)
        lines.extend([line] * scale)
    return lines


def draw(text: str, footer: str, inverted: bool) -> None:
    cols, rows = shutil.get_terminal_size()
    pixel_width = sum(len(FONT[ch][0]) for ch in text) + len(text) - 1
    scale = min(cols // (2 * pixel_width), (rows - 2) // PIXEL_ROWS)
    if scale < 1:
        raise SystemExit(
            f"timer: terminal {cols}x{rows} is too small, "
            f"need at least {2 * pixel_width}x{PIXEL_ROWS + 2}"
        )
    body = big_lines(text, scale)
    top = (rows - len(body) - 2) // 2
    left = " " * ((cols - len(body[0])) // 2)

    out = ["\x1b[7m" if inverted else "\x1b[0m", "\x1b[H"]
    out += ["\x1b[K\n"] * top
    out += [f"{left}{line}\x1b[K\n" for line in body]
    out += ["\x1b[K\n", f"{footer.center(cols)}\x1b[K", "\x1b[J"]
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def run(duration: int, fd: int) -> None:
    remaining = float(duration)  # seconds left as of `resumed`
    resumed: float | None = time.monotonic()  # None while paused

    while True:
        left = remaining - (time.monotonic() - resumed if resumed is not None else 0.0)
        if left <= 0:
            break
        footer = "space pause · r restart · q quit"
        if resumed is None:
            footer = "PAUSED · " + footer
        draw(clock_text(math.ceil(left)), footer, inverted=False)

        if not select.select([fd], [], [], TICK_SECONDS)[0]:
            continue
        key = os.read(fd, 1).decode()
        if key == " ":
            if resumed is None:
                resumed = time.monotonic()
            else:
                remaining = left
                resumed = None
        elif key == "r":
            remaining = float(duration)
            if resumed is not None:
                resumed = time.monotonic()
        elif key == "q":
            return

    inverted = True
    while True:
        draw(
            clock_text(0),
            f"time's up ({clock_text(duration)}) · press any key",
            inverted,
        )
        if inverted:
            sys.stdout.write("\a")
            sys.stdout.flush()
        if select.select([fd], [], [], FLASH_SECONDS)[0]:
            os.read(fd, 1)
            return
        inverted = not inverted


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        raise SystemExit(__doc__.strip())
    duration = parse_duration(sys.argv[1])

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    sys.stdout.write("\x1b[?1049h\x1b[?25l")  # alternate screen, hide cursor
    try:
        run(duration, fd)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


if __name__ == "__main__":
    main()
