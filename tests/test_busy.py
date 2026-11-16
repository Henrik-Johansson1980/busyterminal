"""Unit tests for busy.py's helpers, timing and tasks."""

import argparse
import os
import random
import re
import sys
import termios
import threading
import time
import tty
from collections.abc import Callable, Iterator

import pytest

import busy


@pytest.fixture(autouse=True)
def default_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from main()'s defaults: no color, no deadline, no keys."""
    monkeypatch.setattr(busy, "use_color", False)
    monkeypatch.setattr(busy, "speed", 1.0)
    monkeypatch.setattr(busy, "deadline", None)
    monkeypatch.setattr(busy, "keys_enabled", False)


@pytest.fixture
def fake_stdin(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """Point sys.stdin at a pipe and enable key reading; returns the write end."""
    read_fd, write_fd = os.pipe()
    stdin = os.fdopen(read_fd, "rb", buffering=0)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(busy, "keys_enabled", True)
    yield write_fd
    stdin.close()
    os.close(write_fd)


@pytest.fixture
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make every delay instant, recording the requested seconds."""
    requested: list[float] = []
    monkeypatch.setattr(busy, "wait", requested.append)
    return requested


# --- parse_duration ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("90", 90),
        ("30s", 30),
        ("5m", 300),
        ("1.5h", 5400),
        (" 2M ", 120),
        ("24h", 86400),
    ],
)
def test_parse_duration_accepts_units(text: str, seconds: float) -> None:
    assert busy.parse_duration(text) == seconds


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("soon", "invalid duration"),
        ("-5", "invalid duration"),
        ("5d", "invalid duration"),
        ("0", "greater than zero"),
        ("0s", "greater than zero"),
        ("24.1h", "at most 24h"),
    ],
)
def test_parse_duration_rejects_bad_values(text: str, message: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        busy.parse_duration(text)


# --- parse_speed / parse_args -----------------------------------------------


@pytest.mark.parametrize("text", ["0.05", "0.5", "1", "10"])
def test_parse_speed_accepts_positive_values(text: str) -> None:
    assert busy.parse_speed(text) == float(text)


@pytest.mark.parametrize("text", ["0", "-1", "0.049", "nan"])
def test_parse_speed_rejects_values_below_minimum(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="at least 0.05"):
        busy.parse_speed(text)


def test_parse_speed_rejects_non_numbers() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="invalid speed"):
        busy.parse_speed("fast")


def test_parse_args_defaults() -> None:
    args = busy.parse_args([])
    assert (args.speed, args.no_color, args.duration) == (1.0, False, None)


def test_parse_args_slow_means_half_speed() -> None:
    assert busy.parse_args(["--slow"]).speed == 0.5


def test_parse_args_reads_all_options() -> None:
    args = busy.parse_args(["--speed", "2", "--no-color", "--duration", "5m"])
    assert (args.speed, args.no_color, args.duration) == (2.0, True, 300)


# --- style and fake data ----------------------------------------------------


def test_style_returns_plain_text_without_color() -> None:
    assert busy.style("hello", "red", "bold") == "hello"


def test_style_wraps_text_in_codes_with_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(busy, "use_color", True)
    assert busy.style("hi", "red", "bold") == "\033[31m\033[1mhi\033[0m"


def test_style_without_styles_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(busy, "use_color", True)
    assert busy.style("hi") == "hi"


def test_rand_hex_has_requested_length_and_charset() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", busy.rand_hex(12))


def test_rand_ip_is_four_octets_in_range() -> None:
    octets = [int(part) for part in busy.rand_ip().split(".")]
    assert len(octets) == 4
    assert all(1 <= octet <= 254 for octet in octets)


def test_rand_version_respects_limits() -> None:
    for _ in range(50):
        major, minor, patch = map(int, busy.rand_version(1, 2, 3).split("."))
        assert major <= 1 and minor <= 2 and patch <= 3


@pytest.mark.parametrize("template", busy.LOG_MESSAGES)
def test_fill_log_template_fills_every_placeholder(template: str) -> None:
    filled = busy.fill_log_template(template)
    assert "{" not in filled and "}" not in filled


# --- wait and the deadline --------------------------------------------------


def test_wait_raises_once_deadline_has_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(busy, "deadline", time.monotonic() - 1)
    with pytest.raises(busy.DeadlineReachedError):
        busy.wait(0)


def test_wait_stops_at_deadline_instead_of_sleeping_longer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(busy, "deadline", time.monotonic() + 0.1)
    started = time.monotonic()
    with pytest.raises(busy.DeadlineReachedError):
        busy.wait(5)
    assert time.monotonic() - started < 1


def test_wait_sleeps_requested_time_without_deadline() -> None:
    started = time.monotonic()
    busy.wait(0.1)
    assert 0.09 <= time.monotonic() - started < 0.5


def test_work_delay_is_scaled_by_speed(
    monkeypatch: pytest.MonkeyPatch, no_waiting: list[float]
) -> None:
    monkeypatch.setattr(busy, "speed", 4.0)
    busy.work_delay(2.0)
    busy.work_delay(1.0, 1.0)
    assert no_waiting == [0.5, 0.25]


# --- keys -------------------------------------------------------------------


def test_read_key_returns_none_when_keys_disabled() -> None:
    assert busy.read_key(0) is None


def test_read_key_returns_none_on_timeout(fake_stdin: int) -> None:
    assert busy.read_key(0.01) is None


def test_read_key_returns_pressed_key(fake_stdin: int) -> None:
    os.write(fake_stdin, b"p")
    assert busy.read_key(0.1) == "p"


@pytest.mark.parametrize("key", [b"q", b"Q", b"\x1b"])
def test_read_key_raises_on_quit_keys(fake_stdin: int, key: bytes) -> None:
    os.write(fake_stdin, key)
    with pytest.raises(busy.QuitRequestedError):
        busy.read_key(0.1)


@pytest.mark.parametrize("sequence", [b"\x1b[A", b"\x1b[B", b"\x1bOP"])
def test_read_key_ignores_escape_sequences(fake_stdin: int, sequence: bytes) -> None:
    os.write(fake_stdin, sequence)
    assert busy.read_key(0.1) is None
    assert busy.read_key(0.01) is None  # nothing of the sequence is left over


def test_pause_extends_deadline_by_paused_time(
    fake_stdin: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_deadline = time.monotonic() + 100
    monkeypatch.setattr(busy, "deadline", original_deadline)
    os.write(fake_stdin, b" ")
    started = time.monotonic()

    def resume_later() -> None:
        time.sleep(0.2)
        os.write(fake_stdin, b" ")

    threading.Thread(target=resume_later, daemon=True).start()
    busy.wait(0.05)
    assert time.monotonic() - started >= 0.2
    assert busy.deadline is not None
    assert busy.deadline - original_deadline >= 0.2


def test_quit_key_while_paused_raises(fake_stdin: int) -> None:
    os.write(fake_stdin, b"pq")
    with pytest.raises(busy.QuitRequestedError):
        busy.wait(1)


def test_other_keys_do_not_pause_or_stop(fake_stdin: int) -> None:
    os.write(fake_stdin, b"xyz")
    started = time.monotonic()
    busy.wait(0.1)
    assert time.monotonic() - started < 0.5


# --- progress bar and spinner -----------------------------------------------


def test_progress_bar_ends_full_on_its_own_line(
    capsys: pytest.CaptureFixture[str], no_waiting: list[float]
) -> None:
    busy.progress_bar("pkg", total_time=1, bar_width=10)
    output = capsys.readouterr().out
    assert output.endswith("pkg [##########] 100.0%\n")


def test_progress_bar_accepts_zero_total_time(
    capsys: pytest.CaptureFixture[str], no_waiting: list[float]
) -> None:
    busy.progress_bar("pkg", total_time=0, bar_width=10)
    assert all(seconds == 0 for seconds in no_waiting if seconds < 0.3)


def test_spinner_frame_count_follows_duration_and_speed(
    monkeypatch: pytest.MonkeyPatch, no_waiting: list[float]
) -> None:
    monkeypatch.setattr(busy, "speed", 2.0)
    busy.spinner("step", duration=1.6)
    assert len(no_waiting) == 10  # 1.6s / 2x speed / 0.08s per frame


def test_spinner_draws_at_least_one_frame(
    capsys: pytest.CaptureFixture[str], no_waiting: list[float]
) -> None:
    busy.spinner("step", duration=0)
    assert len(no_waiting) == 1
    assert capsys.readouterr().out.endswith("done step\n")


# --- tasks ------------------------------------------------------------------


@pytest.mark.parametrize("task", busy.TASKS, ids=lambda task: task.__name__)
def test_every_task_completes_and_prints(
    task: Callable[[], None],
    capsys: pytest.CaptureFixture[str],
    no_waiting: list[float],
) -> None:
    task()
    output = capsys.readouterr().out
    assert output.strip()
    assert "\033[3" not in output  # color is off, so no color codes leak


def test_run_tasks_forever_never_repeats_a_task_back_to_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def make_task(name: str) -> Callable[[], None]:
        def task() -> None:
            calls.append(name)
            if len(calls) == 30:
                raise busy.DeadlineReachedError

        return task

    monkeypatch.setattr(busy, "TASKS", [make_task("a"), make_task("b")])
    monkeypatch.setattr(busy, "work_delay", lambda *args: None)
    with pytest.raises(busy.DeadlineReachedError):
        busy.run_tasks_forever()
    # strict=False: calls[1:] is one shorter by design, pairing neighbours.
    assert all(first != second for first, second in zip(calls, calls[1:], strict=False))


# --- sign-off ---------------------------------------------------------------


def test_sign_off_resets_color_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(busy, "use_color", True)
    busy.sign_off("Bye.")
    assert capsys.readouterr().out == "\033[0m\nBye.\n"


def test_sign_off_without_color_prints_plain_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    busy.sign_off("Bye.")
    assert capsys.readouterr().out == "\nBye.\n"


# --- remaining paths --------------------------------------------------------


def test_read_key_without_keys_and_without_timeout_returns_at_once() -> None:
    started = time.monotonic()
    assert busy.read_key(None) is None
    assert time.monotonic() - started < 0.1


def test_other_keys_while_paused_keep_it_paused(fake_stdin: int) -> None:
    os.write(fake_stdin, b" xyz ")
    busy.wait(0.01)  # pauses on " ", ignores "xyz", resumes on " "
    assert busy.read_key(0.01) is None  # every key was consumed


def test_pause_without_deadline_leaves_it_unset(fake_stdin: int) -> None:
    os.write(fake_stdin, b"  ")
    paused_for = busy.wait_while_paused()
    assert paused_for >= 0
    assert busy.deadline is None


def test_progress_bar_and_spinner_pick_defaults(
    capsys: pytest.CaptureFixture[str], no_waiting: list[float]
) -> None:
    busy.progress_bar("pkg")
    busy.spinner("step")
    output = capsys.readouterr().out
    assert "100.0%" in output
    assert output.endswith("done step\n")


def test_compile_sometimes_warns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_waiting: list[float],
) -> None:
    monkeypatch.setattr(random, "random", lambda: 0.0)
    busy.task_compile()
    assert "warning: unused variable" in capsys.readouterr().out


def test_test_run_sometimes_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_waiting: list[float],
) -> None:
    monkeypatch.setattr(random, "random", lambda: 0.0)
    busy.task_tests()
    output = capsys.readouterr().out
    assert "FAILED" in output
    assert " 0 passed," in output


class FakeTerminalStdin:
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


def test_key_input_stays_off_when_terminal_refuses_cbreak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(fd: int) -> None:
        raise termios.error("not supported")

    monkeypatch.setattr(sys, "stdin", FakeTerminalStdin())
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(tty, "setcbreak", refuse)
    assert busy.enable_key_input() is None
    assert busy.keys_enabled is False
