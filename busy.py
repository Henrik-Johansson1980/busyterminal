#!/usr/bin/env python3
"""busy.py: make the terminal look like it is doing serious, important work.

Run it with `python3 busy.py`. Press space (or p) to pause and resume, q, Esc or Ctrl+C to stop.
Time spent paused does not count toward --duration.
Options:
  --speed N   multiply the speed (e.g. 2 = twice as fast, 0.5 = half)
  --slow      run at half speed (same as --speed 0.5)
  --no-color  disable ANSI colors
  --duration  stop after this long, e.g. 90, 30s, 5m, 1.5h; max 24h (default: run forever)
"""

import argparse
import hashlib
import os
import random
import re
import select
import shutil
import string
import sys
import time
from datetime import datetime

try:
    import termios
    import tty
except ImportError:  # not available on Windows; pausing is then disabled
    termios = tty = None

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

USE_COLOR = True
SPEED = 1.0
DEADLINE = None  # time.monotonic() value at which to stop, or None to run forever
MAX_DURATION = 24 * 3600  # longest allowed --duration, in seconds
KEYS_ENABLED = False  # True once stdin is in cbreak mode and keys can be read
PAUSE_KEYS = {" ", "p", "P"}
QUIT_KEYS = {"q", "Q", "\x1b"}  # \x1b is Esc


class TimeUp(Exception):
    """Raised when the --duration deadline is reached."""


class Quit(Exception):
    """Raised when a quit key is pressed."""


def check_deadline():
    if DEADLINE is not None and time.monotonic() >= DEADLINE:
        raise TimeUp


def read_key(timeout):
    """Wait up to `timeout` seconds (None = forever) for a key press; return it or None.

    Raises Quit if a quit key was pressed.
    """
    if not KEYS_ENABLED:
        if timeout is not None:
            time.sleep(timeout)
        return None
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    fd = sys.stdin.fileno()
    key = os.read(fd, 1).decode(errors="ignore")
    if key == "\x1b":
        # Arrow and function keys also start with Esc, followed at once by
        # more bytes. Swallow those sequences; only a lone Esc means quit.
        if select.select([fd], [], [], 0.03)[0]:
            os.read(fd, 32)
            return None
    if key in QUIT_KEYS:
        raise Quit
    return key


def wait_while_paused():
    """Block until a pause key is pressed again. Returns how long we were paused."""
    global DEADLINE
    started = time.monotonic()
    show = sys.stdout.isatty()
    if show:
        # Save the cursor, print the notice, and put everything back on resume,
        # so a half-drawn progress bar or spinner line is left intact.
        sys.stdout.write("\0337" + c("  [paused: press space to resume]", "yellow", "bold"))
        sys.stdout.flush()
    try:
        while read_key(None) not in PAUSE_KEYS:
            pass
    finally:
        # Also clear the notice when quitting while paused.
        if show:
            sys.stdout.write("\0338\033[K")
            sys.stdout.flush()
    paused_for = time.monotonic() - started
    if DEADLINE is not None:
        DEADLINE += paused_for
    return paused_for


def sleep(seconds):
    """Sleep, but never past the deadline, and pause when a pause key is pressed."""
    check_deadline()
    end = time.monotonic() + seconds
    while True:
        now = time.monotonic()
        remaining = end - now
        if DEADLINE is not None:
            remaining = min(remaining, DEADLINE - now)
        if remaining <= 0:
            break
        if read_key(remaining) in PAUSE_KEYS:
            end += wait_while_paused()
    check_deadline()

COLORS = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
    "reset": "\033[0m",
}


def c(text, *styles):
    if not USE_COLOR or not styles:
        return text
    return "".join(COLORS[s] for s in styles) + text + COLORS["reset"]


def out(line=""):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def pause(lo, hi=None):
    delay = lo if hi is None else random.uniform(lo, hi)
    sleep(delay / SPEED)


def width():
    return shutil.get_terminal_size((100, 30)).columns


def timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def rand_hex(n):
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def rand_word():
    return random.choice(WORDS)


def progress_bar(label, total_time=None, bar_width=None):
    """Draw a progress bar that fills up in place, with uneven speed."""
    bar_width = bar_width or max(10, min(40, width() - len(label) - 20))
    total_time = total_time or random.uniform(1.0, 4.0)
    progress = 0.0
    while progress < 1.0:
        # Progress bars never move evenly; stall now and then.
        if random.random() < 0.08:
            pause(0.3, 0.9)
        progress = min(1.0, progress + random.uniform(0.005, 0.06))
        filled = int(bar_width * progress)
        bar = "#" * filled + "-" * (bar_width - filled)
        sys.stdout.write(f"\r{label} [{c(bar, 'green')}] {progress * 100:5.1f}%")
        sys.stdout.flush()
        pause(total_time / 40)
    sys.stdout.write("\n")
    sys.stdout.flush()


def spinner(label, duration=None):
    frames = "|/-\\"
    duration = duration or random.uniform(0.8, 2.5)
    # Count frames rather than watching the clock, so a pause mid-spin
    # does not make the spinner finish instantly on resume.
    for i in range(max(1, round(duration / SPEED / 0.08))):
        sys.stdout.write(f"\r{c(frames[i % 4], 'cyan')} {label}")
        sys.stdout.flush()
        sleep(0.08)
    sys.stdout.write(f"\r\033[K{c('done', 'green')} {label}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

WORDS = [
    "core", "engine", "parser", "kernel", "cache", "router", "scheduler",
    "session", "auth", "billing", "ledger", "index", "shard", "buffer",
    "socket", "stream", "worker", "pipeline", "matrix", "vector", "tensor",
    "graph", "node", "cluster", "quantum", "flux", "vault", "beacon",
]

PACKAGES = [
    "left-pad", "lodash", "react-dom", "numpy", "tokio", "serde", "openssl",
    "libxml2", "zlib", "protobuf", "grpcio", "chromium-sandbox", "webpack",
    "esbuild", "cryptography", "pandas", "scipy", "tensorflow-lite", "rustls",
    "hyper", "boost", "eigen", "ffmpeg", "sqlite3", "redis-client",
]

LOG_MESSAGES = [
    "Accepted connection from {ip}:{port}",
    "Cache miss for key {hex}, fetching from origin",
    "Flushed {n} dirty pages to disk",
    "Rebalancing shard {n} across {m} nodes",
    "GC pause {ms}ms, heap {n}MB / {m}MB",
    "Request {hex} completed in {ms}ms",
    "Renewed lease for worker-{n}",
    "Compacting segment {hex}",
    "Replicated {n} records to replica-{m}",
    "Health check passed for {word}-service",
    "Retrying upstream call to {word}-api (attempt {small})",
    "Spawned {small} workers for queue '{word}'",
    "Checkpoint written at offset {n}",
    "TLS handshake completed with {ip}",
    "Evicted {n} stale entries from {word} cache",
]

LEVELS = [
    ("INFO", "green", 70),
    ("DEBUG", "gray", 18),
    ("WARN", "yellow", 9),
    ("ERROR", "red", 3),
]


def fill(template):
    return template.format(
        ip=".".join(str(random.randint(1, 254)) for _ in range(4)),
        port=random.randint(1024, 65535),
        hex=rand_hex(8),
        n=random.randint(10, 99999),
        m=random.randint(2, 64),
        ms=random.randint(1, 900),
        word=rand_word(),
        small=random.randint(2, 9),
    )


# ---------------------------------------------------------------------------
# Tasks: each one prints a burst of fake work
# ---------------------------------------------------------------------------


def task_compile():
    project = f"{rand_word()}-{rand_word()}"
    out(c(f"$ make -j{random.choice([4, 8, 16])} {project}", "bold"))
    for _ in range(random.randint(8, 25)):
        folder = random.choice(["src", "lib", "src/core", "src/net", "vendor"])
        name = f"{rand_word()}_{rand_word()}.{random.choice(['c', 'cpp', 'rs'])}"
        out(f"  {c('CC', 'cyan')}      {folder}/{name}")
        if random.random() < 0.07:
            out(c(f"  warning: unused variable '{rand_word()}' [-Wunused-variable]", "yellow"))
        pause(0.03, 0.25)
    out(f"  {c('LD', 'magenta')}      build/{project}")
    pause(0.4, 1.0)
    out(c(f"Build finished: build/{project} ({random.randint(200, 9000)} KB)", "green"))


def task_install():
    tool = random.choice(["npm install", "pip install -r requirements.txt", "cargo fetch"])
    out(c(f"$ {tool}", "bold"))
    for pkg in random.sample(PACKAGES, random.randint(4, 9)):
        version = f"{random.randint(0, 9)}.{random.randint(0, 30)}.{random.randint(0, 20)}"
        progress_bar(f"  {pkg}@{version}".ljust(30), total_time=random.uniform(0.4, 1.6))
    out(c(f"added {random.randint(50, 1400)} packages in {random.uniform(2, 40):.1f}s", "green"))


def task_logs():
    service = f"{rand_word()}-service"
    out(c(f"$ tail -f /var/log/{service}.log", "bold"))
    for _ in range(random.randint(15, 45)):
        level, color, _ = random.choices(LEVELS, weights=[w for _, _, w in LEVELS])[0]
        msg = fill(random.choice(LOG_MESSAGES))
        out(f"{c(timestamp(), 'gray')} {c(level.ljust(5), color)} [{rand_word()}] {msg}")
        pause(0.02, 0.35)


def task_hexdump():
    target = f"/dev/{random.choice(['sda', 'nvme0n1', 'mem'])}"
    out(c(f"$ xxd -s 0x{rand_hex(6)} -l 512 {target}", "bold"))
    addr = random.randint(0, 0xFFFFFF)
    for _ in range(random.randint(10, 30)):
        raw = bytes(random.randint(0, 255) for _ in range(16))
        hexpart = " ".join(raw[i:i + 2].hex() for i in range(0, 16, 2))
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
        out(f"{c(f'{addr:08x}', 'cyan')}: {hexpart}  {c(text, 'dim')}")
        addr += 16
        pause(0.01, 0.06)


def task_tests():
    suite = f"{rand_word()}_{rand_word()}"
    out(c(f"$ pytest tests/test_{suite}.py -v", "bold"))
    passed = failed = 0
    for _ in range(random.randint(8, 22)):
        name = f"test_{rand_word()}_{random.choice(['handles', 'rejects', 'returns', 'parses'])}_{rand_word()}"
        pause(0.05, 0.4)
        if random.random() < 0.05:
            failed += 1
            out(f"  {name} {c('FAILED', 'red')}")
        else:
            passed += 1
            out(f"  {name} {c('PASSED', 'green')}")
    color = "red" if failed else "green"
    out(c(f"===== {passed} passed, {failed} failed in {random.uniform(0.5, 12):.2f}s =====", color))


def task_migration():
    out(c("$ ./manage migrate --database=production", "bold"))
    for i in range(random.randint(3, 8)):
        name = f"{random.randint(1000, 9999)}_{random.choice(['add', 'drop', 'alter', 'index'])}_{rand_word()}_{rand_word()}"
        spinner(f"Applying {name}", random.uniform(0.4, 1.8))
    out(c("All migrations applied.", "green"))


def task_hashing():
    out(c("$ sha256sum ./dist/*", "bold"))
    for _ in range(random.randint(5, 15)):
        name = f"{rand_word()}-{random.randint(1, 9)}.{random.randint(0, 20)}.{random.choice(['tar.gz', 'whl', 'bin', 'img'])}"
        digest = hashlib.sha256(os.urandom(32)).hexdigest()
        out(f"{c(digest, 'yellow')}  {name}")
        pause(0.05, 0.3)


def task_matrix():
    cols = width()
    out(c("Decrypting data stream...", "bold"))
    chars = string.ascii_letters + string.digits + "@#$%&*"
    for _ in range(random.randint(10, 25)):
        line = "".join(random.choice(chars) if random.random() < 0.5 else " " for _ in range(cols - 1))
        out(c(line, random.choice(["green", "green", "dim"])))
        pause(0.03, 0.08)
    out(c(f"Stream decoded: {random.randint(1, 900)} MB, checksum OK", "green"))


def task_network():
    host = f"{rand_word()}.{random.choice(['internal', 'prod', 'cluster.local'])}"
    out(c(f"$ ping -c 6 {host}", "bold"))
    ip = ".".join(str(random.randint(1, 254)) for _ in range(4))
    for seq in range(6):
        out(f"64 bytes from {ip}: icmp_seq={seq} ttl=64 time={random.uniform(0.2, 40):.2f} ms")
        pause(0.3, 0.7)
    out(c("6 packets transmitted, 6 received, 0% packet loss", "green"))


def task_deploy():
    env = random.choice(["staging", "production", "eu-west-1", "us-east-2"])
    out(c(f"$ deploy --env {env} --tag v{random.randint(1, 9)}.{random.randint(0, 40)}.{random.randint(0, 99)}", "bold"))
    steps = [
        "Building container image",
        "Pushing image to registry",
        "Running database preflight checks",
        "Draining old instances",
        "Rolling out new pods",
        "Warming caches",
        "Verifying health endpoints",
    ]
    for step in steps:
        spinner(step, random.uniform(0.5, 2.0))
    out(c(f"Deployment to {env} succeeded.", "green", "bold"))


def task_data_processing():
    out(c(f"$ python etl.py --source s3://{rand_word()}-lake --batch-size 10000", "bold"))
    total = random.randint(200_000, 5_000_000)
    done = 0
    while done < total:
        done = min(total, done + random.randint(total // 30, total // 8))
        rate = random.randint(8_000, 90_000)
        out(f"[{c(timestamp(), 'gray')}] processed {done:>10,} / {total:,} rows  ({rate:,} rows/s)")
        pause(0.2, 0.6)
    out(c("ETL job complete. Output written to warehouse.", "green"))


TASKS = [
    task_compile,
    task_install,
    task_logs,
    task_hexdump,
    task_tests,
    task_migration,
    task_hashing,
    task_matrix,
    task_network,
    task_deploy,
    task_data_processing,
]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def parse_duration(value):
    """Turn '90', '30s', '5m' or '1.5h' into seconds."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", value.lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid duration '{value}' (use e.g. 90, 30s, 5m or 1.5h)"
        )
    seconds = float(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]
    if seconds <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    if seconds > MAX_DURATION:
        raise argparse.ArgumentTypeError(
            f"duration can be at most {MAX_DURATION // 3600}h"
        )
    return seconds


def main():
    global USE_COLOR, SPEED, DEADLINE, KEYS_ENABLED

    parser = argparse.ArgumentParser(description="Look busy.")
    pace = parser.add_mutually_exclusive_group()
    pace.add_argument("--speed", type=float, default=1.0, help="speed multiplier (default 1.0)")
    pace.add_argument(
        "--slow",
        dest="speed",
        action="store_const",
        const=0.5,
        help="run at half speed (same as --speed 0.5)",
    )
    parser.add_argument("--no-color", action="store_true", help="disable colors")
    parser.add_argument(
        "--duration",
        type=parse_duration,
        metavar="TIME",
        help="stop after this long, e.g. 90, 30s, 5m, 1.5h; max 24h (default: run forever)",
    )
    args = parser.parse_args()

    if args.duration is not None:
        DEADLINE = time.monotonic() + args.duration

    SPEED = max(0.05, args.speed)
    USE_COLOR = not args.no_color and sys.stdout.isatty()

    # cbreak mode lets us read single key presses without Enter and without
    # echoing them; Ctrl+C still works. The old settings are restored on exit.
    saved_tty = None
    if termios is not None and sys.stdin.isatty():
        try:
            saved_tty = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            KEYS_ENABLED = True
        except termios.error:
            saved_tty = None

    if sys.stdout.isatty():
        # Push everything already on screen (including the command that
        # started us) up into the scrollback, then start at the top.
        rows = shutil.get_terminal_size((100, 30)).lines
        sys.stdout.write("\n" * rows + "\033[H")
        sys.stdout.flush()

    last = None
    try:
        while True:
            task = random.choice([t for t in TASKS if t is not last])
            last = task
            task()
            out()
            pause(0.3, 1.5)
    except TimeUp:
        sys.stdout.write(COLORS["reset"] if USE_COLOR else "")
        out()
        out("Shift complete. Great job today.")
    except (KeyboardInterrupt, Quit):
        sys.stdout.write(COLORS["reset"] if USE_COLOR else "")
        out()
        out("Work interrupted. Great job today.")
    finally:
        if saved_tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_tty)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Whatever we were piped into (e.g. `| head`) stopped reading. Point
        # stdout at /dev/null so Python's final flush at exit cannot raise a
        # second BrokenPipeError, then exit quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
