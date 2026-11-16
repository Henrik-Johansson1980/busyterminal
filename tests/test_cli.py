"""End-to-end tests: run busy.py as a real process, piped or in a pseudo-terminal."""

import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "busy.py")


def run_piped(*args: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TerminalSession:
    """busy.py running in a pseudo-terminal, so it sees a real tty."""

    def __init__(self, *args: str, rows: int = 24, cols: int = 100) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execv(sys.executable, [sys.executable, SCRIPT, *args])
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.output = b""
        self.exit_status: int | None = None

    def read_for(self, seconds: float) -> bytes:
        """Collect output for `seconds`; return only what arrived in that window."""
        received = b""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:  # the child exited and closed the terminal
                    break
                if not chunk:
                    break
                received += chunk
        self.output += received
        return received

    def press(self, key: bytes) -> None:
        os.write(self.fd, key)

    def has_exited(self) -> bool:
        if self.exit_status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.exit_status = status
        return self.exit_status is not None

    def echo_enabled(self) -> bool:
        return bool(termios.tcgetattr(self.fd)[3] & termios.ECHO)

    def close(self) -> None:
        if not self.has_exited():
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        os.close(self.fd)


def wait_until_exited(session: TerminalSession, timeout: float = 5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        session.read_for(0.1)
        if session.has_exited():
            return True
    return False


# --- piped (no terminal) ---------------------------------------------------


def test_duration_ends_shift_with_sign_off() -> None:
    result = run_piped("--duration", "1", "--speed", "5")
    assert result.returncode == 0
    assert result.stdout.rstrip().endswith("Shift complete. Great job today.")


def test_piped_output_has_no_color_codes_or_scroll_padding() -> None:
    result = run_piped("--duration", "1")
    assert "\033" not in result.stdout
    assert not result.stdout.startswith("\n")


def test_closed_pipe_exits_without_traceback() -> None:
    proc = subprocess.Popen(
        [sys.executable, SCRIPT, "--speed", "5"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None
    proc.stdout.readline()
    proc.stdout.close()
    proc.wait(timeout=10)
    assert proc.returncode == 1
    assert proc.stderr.read() == b""


def test_invalid_duration_is_rejected() -> None:
    result = run_piped("--duration", "soon")
    assert result.returncode == 2
    assert "invalid duration" in result.stderr


def test_speed_and_slow_cannot_be_combined() -> None:
    result = run_piped("--speed", "2", "--slow")
    assert result.returncode == 2
    assert "not allowed with" in result.stderr


def test_speed_below_minimum_is_rejected() -> None:
    for value in ("0", "-1", "0.01"):
        result = run_piped("--speed", value)
        assert result.returncode == 2, value
        assert "speed must be at least" in result.stderr


# --- in a terminal ----------------------------------------------------------


def test_startup_scrolls_previous_screen_out_of_view() -> None:
    session = TerminalSession("--duration", "1", rows=24)
    try:
        wait_until_exited(session)
        # pty turns each \n into \r\n
        assert session.output.startswith(b"\r\n" * 24 + b"\033[H")
    finally:
        session.close()


def test_pause_stops_output_and_does_not_count_toward_duration() -> None:
    session = TerminalSession("--duration", "2", "--speed", "3")
    try:
        started = time.monotonic()
        session.read_for(0.5)
        session.press(b" ")
        session.read_for(0.3)  # let the notice and in-flight output arrive
        assert b"[paused: press space to resume]" in session.output
        assert session.read_for(1.5) == b""
        session.press(b" ")
        assert wait_until_exited(session)
        elapsed = time.monotonic() - started
        assert elapsed >= 3.5, f"paused time was counted, ran only {elapsed:.1f}s"
        assert b"Shift complete" in session.output
    finally:
        session.close()


def check_key_quits(*keys: bytes) -> None:
    session = TerminalSession()
    try:
        session.read_for(0.5)
        for key in keys:
            session.press(key)
            session.read_for(0.3)
        assert wait_until_exited(session), f"{keys!r} did not quit"
        assert session.exit_status is not None
        assert os.WEXITSTATUS(session.exit_status) == 0
        assert b"Work interrupted. Great job today." in session.output
    finally:
        session.close()


def test_q_quits() -> None:
    check_key_quits(b"q")


def test_esc_quits() -> None:
    check_key_quits(b"\x1b")


def test_esc_quits_while_paused() -> None:
    check_key_quits(b" ", b"\x1b")


def test_arrow_key_does_not_quit() -> None:
    session = TerminalSession()
    try:
        session.read_for(0.5)
        session.press(b"\x1b[A")
        session.read_for(1.0)
        assert not session.has_exited()
    finally:
        session.close()


def test_terminal_echo_is_restored_after_quitting() -> None:
    session = TerminalSession()
    try:
        session.read_for(0.5)
        assert not session.echo_enabled()  # cbreak mode while running
        session.press(b"q")
        assert wait_until_exited(session)
        assert session.echo_enabled()
    finally:
        session.close()
