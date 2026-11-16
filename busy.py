#!/usr/bin/env python3
"""busy.py: make the terminal look like it is doing serious, important work.

Run it with `python3 busy.py`.
Keys: space (or p) pauses and resumes; q, Esc or Ctrl+C stops.
Time spent paused does not count toward --duration.
Options:
  --speed N   multiply the speed (e.g. 2 = twice as fast, 0.5 = half)
  --slow      run at half speed (same as --speed 0.5)
  --no-color  disable ANSI colors
  --duration  stop after this long, e.g. 90, 30s, 5m, 1.5h; max 24h
              (default: run forever)
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
from collections.abc import Callable
from datetime import datetime
from typing import Any

# Not available on Windows, where pausing and quit keys are disabled. A
# platform check (unlike try/except ImportError) is understood by type checkers.
if sys.platform != "win32":
    import termios
    import tty

# ---------------------------------------------------------------------------
# Settings and run state
# ---------------------------------------------------------------------------

MAX_DURATION_SECONDS = 24 * 3600
MIN_SPEED = 0.05
SPINNER_FRAME_SECONDS = 0.08
FALLBACK_TERMINAL_SIZE = (100, 30)
PAUSE_KEYS = {" ", "p", "P"}
ESC = "\x1b"
QUIT_KEYS = {"q", "Q", ESC}

# Set once by main() from the command line. Plain module globals keep this
# single-file script simple; tests override them with monkeypatch.
use_color = True
speed = 1.0
deadline: float | None = None  # time.monotonic() value to stop at; None = never
keys_enabled = False  # True once stdin is in cbreak mode and keys can be read


class DeadlineReachedError(Exception):
    """The --duration deadline has passed."""


class QuitRequestedError(Exception):
    """The user pressed a quit key."""


# ---------------------------------------------------------------------------
# Timing, keys and pausing
# ---------------------------------------------------------------------------


def check_deadline() -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise DeadlineReachedError


def read_key(timeout: float | None) -> str | None:
    """Wait up to `timeout` seconds (None = forever) for a key; return it or None.

    Raises QuitRequestedError if a quit key was pressed.
    """
    if not keys_enabled:
        if timeout is not None:
            time.sleep(timeout)
        return None
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    fd = sys.stdin.fileno()
    key = os.read(fd, 1).decode(errors="ignore")
    # Arrow and function keys also start with Esc, followed at once by more
    # bytes. Swallow those sequences; only a lone Esc means quit.
    if key == ESC and select.select([fd], [], [], 0.03)[0]:
        os.read(fd, 32)
        return None
    if key in QUIT_KEYS:
        raise QuitRequestedError
    return key


def wait_while_paused() -> float:
    """Block until a pause key is pressed again. Returns how long we were paused.

    The paused time is added to the deadline, so breaks do not shorten a shift.
    """
    global deadline
    started = time.monotonic()
    draw_notice = sys.stdout.isatty()
    if draw_notice:
        # Save the cursor, print the notice, and restore it on resume, so a
        # half-drawn progress bar or spinner line is left intact.
        notice = style("  [paused: press space to resume]", "yellow", "bold")
        sys.stdout.write("\0337" + notice)
        sys.stdout.flush()
    try:
        while read_key(None) not in PAUSE_KEYS:
            pass
    finally:
        # Runs on quit too, so the notice never lingers above the sign-off.
        if draw_notice:
            sys.stdout.write("\0338\033[K")
            sys.stdout.flush()
    paused_for = time.monotonic() - started
    if deadline is not None:
        deadline += paused_for
    return paused_for


def wait(seconds: float) -> None:
    """Wait `seconds`, never past the deadline, pausing when a pause key is hit."""
    check_deadline()
    end = time.monotonic() + seconds
    while True:
        now = time.monotonic()
        remaining = end - now
        if deadline is not None:
            remaining = min(remaining, deadline - now)
        if remaining <= 0:
            break
        if read_key(remaining) in PAUSE_KEYS:
            end += wait_while_paused()
    check_deadline()


def work_delay(low: float, high: float | None = None) -> None:
    """Wait a random time between `low` and `high` seconds, scaled by --speed."""
    seconds = low if high is None else random.uniform(low, high)
    wait(seconds / speed)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

STYLES = {
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


def style(text: str, *styles: str) -> str:
    if not use_color or not styles:
        return text
    return "".join(STYLES[name] for name in styles) + text + STYLES["reset"]


def print_line(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def print_in_place(line: str) -> None:
    """Redraw the current line, for progress bars and spinners."""
    sys.stdout.write("\r" + line)
    sys.stdout.flush()


def terminal_columns() -> int:
    return shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).columns


def terminal_rows() -> int:
    return shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).lines


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def progress_bar(
    label: str, total_time: float | None = None, bar_width: int | None = None
) -> None:
    """Draw a progress bar that fills up in place, with uneven speed."""
    if bar_width is None:
        bar_width = max(10, min(40, terminal_columns() - len(label) - 20))
    if total_time is None:
        total_time = random.uniform(1.0, 4.0)
    progress = 0.0
    while progress < 1.0:
        # Progress bars never move evenly; stall now and then.
        if random.random() < 0.08:
            work_delay(0.3, 0.9)
        progress = min(1.0, progress + random.uniform(0.005, 0.06))
        filled = int(bar_width * progress)
        bar = "#" * filled + "-" * (bar_width - filled)
        print_in_place(f"{label} [{style(bar, 'green')}] {progress * 100:5.1f}%")
        work_delay(total_time / 40)
    print_line()


def spinner(label: str, duration: float | None = None) -> None:
    frames = "|/-\\"
    if duration is None:
        duration = random.uniform(0.8, 2.5)
    # Count frames rather than watching the clock, so a pause mid-spin does
    # not make the spinner finish instantly on resume.
    frame_count = max(1, round(duration / speed / SPINNER_FRAME_SECONDS))
    for i in range(frame_count):
        print_in_place(f"{style(frames[i % len(frames)], 'cyan')} {label}")
        wait(SPINNER_FRAME_SECONDS)
    print_in_place(f"\033[K{style('done', 'green')} {label}\n")


# ---------------------------------------------------------------------------
# Vocabulary and random fake data
# ---------------------------------------------------------------------------

WORDS = [
    "core", "engine", "parser", "kernel", "cache", "router", "scheduler",
    "session", "auth", "billing", "ledger", "index", "shard", "buffer",
    "socket", "stream", "worker", "pipeline", "matrix", "vector", "tensor",
    "graph", "node", "cluster", "quantum", "flux", "vault", "beacon",
]  # fmt: skip

PACKAGES = [
    "left-pad", "lodash", "react-dom", "numpy", "tokio", "serde", "openssl",
    "libxml2", "zlib", "protobuf", "grpcio", "chromium-sandbox", "webpack",
    "esbuild", "cryptography", "pandas", "scipy", "tensorflow-lite", "rustls",
    "hyper", "boost", "eigen", "ffmpeg", "sqlite3", "redis-client",
]  # fmt: skip

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

LOG_LEVELS = [  # (name, color, relative frequency)
    ("INFO", "green", 70),
    ("DEBUG", "gray", 18),
    ("WARN", "yellow", 9),
    ("ERROR", "red", 3),
]


def rand_hex(length: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(length))


def rand_word() -> str:
    return random.choice(WORDS)


def rand_ip() -> str:
    return ".".join(str(random.randint(1, 254)) for _ in range(4))


def rand_version(max_major: int = 9, max_minor: int = 30, max_patch: int = 20) -> str:
    major = random.randint(0, max_major)
    minor = random.randint(0, max_minor)
    patch = random.randint(0, max_patch)
    return f"{major}.{minor}.{patch}"


def fill_log_template(template: str) -> str:
    return template.format(
        ip=rand_ip(),
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


def task_compile() -> None:
    project = f"{rand_word()}-{rand_word()}"
    print_line(style(f"$ make -j{random.choice([4, 8, 16])} {project}", "bold"))
    for _ in range(random.randint(8, 25)):
        folder = random.choice(["src", "lib", "src/core", "src/net", "vendor"])
        name = f"{rand_word()}_{rand_word()}.{random.choice(['c', 'cpp', 'rs'])}"
        print_line(f"  {style('CC', 'cyan')}      {folder}/{name}")
        if random.random() < 0.07:
            warning = f"  warning: unused variable '{rand_word()}' [-Wunused-variable]"
            print_line(style(warning, "yellow"))
        work_delay(0.03, 0.25)
    print_line(f"  {style('LD', 'magenta')}      build/{project}")
    work_delay(0.4, 1.0)
    size_kb = random.randint(200, 9000)
    print_line(style(f"Build finished: build/{project} ({size_kb} KB)", "green"))


def task_install() -> None:
    tool = random.choice(
        ["npm install", "pip install -r requirements.txt", "cargo fetch"]
    )
    print_line(style(f"$ {tool}", "bold"))
    for package in random.sample(PACKAGES, random.randint(4, 9)):
        label = f"  {package}@{rand_version()}".ljust(30)
        progress_bar(label, total_time=random.uniform(0.4, 1.6))
    count = random.randint(50, 1400)
    seconds = random.uniform(2, 40)
    print_line(style(f"added {count} packages in {seconds:.1f}s", "green"))


def task_logs() -> None:
    service = f"{rand_word()}-service"
    print_line(style(f"$ tail -f /var/log/{service}.log", "bold"))
    weights = [frequency for _, _, frequency in LOG_LEVELS]
    for _ in range(random.randint(15, 45)):
        level, color, _ = random.choices(LOG_LEVELS, weights=weights)[0]
        message = fill_log_template(random.choice(LOG_MESSAGES))
        time_part = style(timestamp(), "gray")
        level_part = style(level.ljust(5), color)
        print_line(f"{time_part} {level_part} [{rand_word()}] {message}")
        work_delay(0.02, 0.35)


def task_hexdump() -> None:
    target = f"/dev/{random.choice(['sda', 'nvme0n1', 'mem'])}"
    print_line(style(f"$ xxd -s 0x{rand_hex(6)} -l 512 {target}", "bold"))
    address = random.randint(0, 0xFFFFFF)
    for _ in range(random.randint(10, 30)):
        raw = bytes(random.randint(0, 255) for _ in range(16))
        hex_part = " ".join(raw[i : i + 2].hex() for i in range(0, 16, 2))
        text_part = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
        address_part = style(f"{address:08x}", "cyan")
        print_line(f"{address_part}: {hex_part}  {style(text_part, 'dim')}")
        address += 16
        work_delay(0.01, 0.06)


def task_tests() -> None:
    suite = f"{rand_word()}_{rand_word()}"
    print_line(style(f"$ pytest tests/test_{suite}.py -v", "bold"))
    passed = failed = 0
    verbs = ["handles", "rejects", "returns", "parses"]
    for _ in range(random.randint(8, 22)):
        name = f"test_{rand_word()}_{random.choice(verbs)}_{rand_word()}"
        work_delay(0.05, 0.4)
        if random.random() < 0.05:
            failed += 1
            print_line(f"  {name} {style('FAILED', 'red')}")
        else:
            passed += 1
            print_line(f"  {name} {style('PASSED', 'green')}")
    seconds = random.uniform(0.5, 12)
    summary = f"===== {passed} passed, {failed} failed in {seconds:.2f}s ====="
    print_line(style(summary, "red" if failed else "green"))


def task_migration() -> None:
    print_line(style("$ ./manage migrate --database=production", "bold"))
    actions = ["add", "drop", "alter", "index"]
    for _ in range(random.randint(3, 8)):
        number = random.randint(1000, 9999)
        name = f"{number}_{random.choice(actions)}_{rand_word()}_{rand_word()}"
        spinner(f"Applying {name}", random.uniform(0.4, 1.8))
    print_line(style("All migrations applied.", "green"))


def task_hashing() -> None:
    print_line(style("$ sha256sum ./dist/*", "bold"))
    extensions = ["tar.gz", "whl", "bin", "img"]
    for _ in range(random.randint(5, 15)):
        version = f"{random.randint(1, 9)}.{random.randint(0, 20)}"
        name = f"{rand_word()}-{version}.{random.choice(extensions)}"
        digest = hashlib.sha256(os.urandom(32)).hexdigest()
        print_line(f"{style(digest, 'yellow')}  {name}")
        work_delay(0.05, 0.3)


def task_matrix() -> None:
    columns = terminal_columns()
    print_line(style("Decrypting data stream...", "bold"))
    chars = string.ascii_letters + string.digits + "@#$%&*"
    for _ in range(random.randint(10, 25)):
        line = "".join(
            random.choice(chars) if random.random() < 0.5 else " "
            for _ in range(columns - 1)
        )
        print_line(style(line, random.choice(["green", "green", "dim"])))
        work_delay(0.03, 0.08)
    size_mb = random.randint(1, 900)
    print_line(style(f"Stream decoded: {size_mb} MB, checksum OK", "green"))


def task_network() -> None:
    domain = random.choice(["internal", "prod", "cluster.local"])
    print_line(style(f"$ ping -c 6 {rand_word()}.{domain}", "bold"))
    ip = rand_ip()
    for sequence in range(6):
        latency = random.uniform(0.2, 40)
        print_line(
            f"64 bytes from {ip}: icmp_seq={sequence} ttl=64 time={latency:.2f} ms"
        )
        work_delay(0.3, 0.7)
    print_line(style("6 packets transmitted, 6 received, 0% packet loss", "green"))


def task_deploy() -> None:
    env = random.choice(["staging", "production", "eu-west-1", "us-east-2"])
    tag = rand_version(max_minor=40, max_patch=99)
    print_line(style(f"$ deploy --env {env} --tag v{tag}", "bold"))
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
    print_line(style(f"Deployment to {env} succeeded.", "green", "bold"))


def task_data_processing() -> None:
    source = f"s3://{rand_word()}-lake"
    print_line(style(f"$ python etl.py --source {source} --batch-size 10000", "bold"))
    total = random.randint(200_000, 5_000_000)
    done = 0
    while done < total:
        done = min(total, done + random.randint(total // 30, total // 8))
        rate = random.randint(8_000, 90_000)
        time_part = style(timestamp(), "gray")
        print_line(
            f"[{time_part}] processed {done:>10,} / {total:,} rows  ({rate:,} rows/s)"
        )
        work_delay(0.2, 0.6)
    print_line(style("ETL job complete. Output written to warehouse.", "green"))


TASKS: list[Callable[[], None]] = [
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
# Command line and main loop
# ---------------------------------------------------------------------------


def parse_duration(value: str) -> float:
    """Turn '90', '30s', '5m' or '1.5h' into seconds."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", value.lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid duration '{value}' (use e.g. 90, 30s, 5m or 1.5h)"
        )
    unit_seconds = {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]
    seconds = float(match.group(1)) * unit_seconds
    if seconds <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    if seconds > MAX_DURATION_SECONDS:
        raise argparse.ArgumentTypeError(
            f"duration can be at most {MAX_DURATION_SECONDS // 3600}h"
        )
    return seconds


def parse_speed(value: str) -> float:
    try:
        multiplier = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid speed '{value}'") from None
    if not multiplier >= MIN_SPEED:  # also rejects nan
        raise argparse.ArgumentTypeError(f"speed must be at least {MIN_SPEED}")
    return multiplier


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Look busy.")
    pace = parser.add_mutually_exclusive_group()
    pace.add_argument(
        "--speed",
        type=parse_speed,
        default=1.0,
        help="speed multiplier (default 1.0)",
    )
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
        help="stop after this long, e.g. 90, 30s, 5m, 1.5h; max 24h "
        "(default: run forever)",
    )
    return parser.parse_args(argv)


TerminalSettings = list[Any]  # as returned by termios.tcgetattr()


def enable_key_input() -> TerminalSettings | None:
    """Put the terminal in cbreak mode, so single key presses can be read.

    Keys are read without Enter and are not echoed; Ctrl+C still works.
    Returns the previous settings for restore_key_input(), or None if stdin
    is not a terminal.
    """
    global keys_enabled
    if sys.platform == "win32" or not sys.stdin.isatty():
        return None
    try:
        saved_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
    except termios.error:
        return None
    keys_enabled = True
    return saved_settings


def restore_key_input(saved_settings: TerminalSettings | None) -> None:
    global keys_enabled
    keys_enabled = False
    if sys.platform != "win32" and saved_settings is not None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_settings)


def scroll_prompt_out_of_view() -> None:
    """Push everything on screen (including the command that started us) into
    the scrollback and start at the top, so nobody sees `python3 busy.py`."""
    sys.stdout.write("\n" * terminal_rows() + "\033[H")
    sys.stdout.flush()


def run_tasks_forever() -> None:
    previous = None
    while True:
        task = random.choice([t for t in TASKS if t is not previous])
        previous = task
        task()
        print_line()
        work_delay(0.3, 1.5)


def sign_off(message: str) -> None:
    # A task may have been stopped mid-line, with a color still active.
    if use_color:
        sys.stdout.write(STYLES["reset"])
    print_line()
    print_line(message)


def main(argv: list[str] | None = None) -> None:
    global use_color, speed, deadline
    args = parse_args(argv)
    speed = args.speed
    use_color = not args.no_color and sys.stdout.isatty()
    if args.duration is not None:
        deadline = time.monotonic() + args.duration

    saved_settings = enable_key_input()
    try:
        if sys.stdout.isatty():
            scroll_prompt_out_of_view()
        run_tasks_forever()
    except DeadlineReachedError:
        sign_off("Shift complete. Great job today.")
    except (KeyboardInterrupt, QuitRequestedError):
        sign_off("Work interrupted. Great job today.")
    finally:
        restore_key_input(saved_settings)


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
