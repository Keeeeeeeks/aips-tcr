#!/usr/bin/env python3
"""Manage the daily MuzAIk radio live window.

The intended policy is simple: the conductor should be running from 5:00 AM
through 7:00 PM America/New_York, then stopped outside that window. This helper
is deliberately small so it can be called by cron, systemd timers, deploy hooks,
or an operator shell.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("AIPS_STATE_DIR", ROOT / ".aips-state" / "radio-state"))
PID_PATH = STATE_DIR / "segment-conductor.pid"
LOG_PATH = STATE_DIR / "segment-conductor.log"
RADIO_TZ = ZoneInfo("America/New_York")
LIVE_START_HOUR = int(os.environ.get("AIPS_RADIO_LIVE_START_HOUR", "5"))
LIVE_END_HOUR = int(os.environ.get("AIPS_RADIO_LIVE_END_HOUR", "19"))


def in_live_window(now: datetime | None = None) -> bool:
    current = now or datetime.now(RADIO_TZ)
    start = current.replace(hour=LIVE_START_HOUR, minute=0, second=0, microsecond=0)
    end = current.replace(hour=LIVE_END_HOUR, minute=0, second=0, microsecond=0)
    return start <= current < end


def next_transition(now: datetime | None = None) -> datetime:
    current = now or datetime.now(RADIO_TZ)
    target_hour = LIVE_END_HOUR if in_live_window(current) else LIVE_START_HOUR
    target = current.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if target <= current:
        target = target + timedelta(days=1)
    return target


def read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text().strip())
    except ValueError:
        return None


def process_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def conductor_running() -> bool:
    return process_running(read_pid())


def start_conductor(args: argparse.Namespace) -> None:
    if conductor_running():
        print(f"segment_conductor already running with pid {read_pid()}")
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "segment_conductor.py"),
        "--session-id",
        args.session_id,
        "--section-bars",
        str(args.section_bars),
        "--prebuffer-sections",
        str(args.prebuffer_sections),
        "--max-recording-seconds",
        str(args.max_recording_seconds),
        "--agent-mode",
        args.agent_mode,
    ]
    if args.soundfont:
        command.extend(["--soundfont", args.soundfont])
    log_handle = LOG_PATH.open("a", encoding="utf-8")
    process = subprocess.Popen(command, cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True)
    PID_PATH.write_text(str(process.pid) + "\n")
    print(f"started segment_conductor pid {process.pid}; logs: {LOG_PATH}")


def stop_conductor() -> None:
    pid = read_pid()
    if not process_running(pid):
        if PID_PATH.exists():
            PID_PATH.unlink()
        print("segment_conductor is not running")
        return
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    print(f"sent SIGTERM to segment_conductor pid {pid}")


def print_status() -> None:
    now = datetime.now(RADIO_TZ)
    state = "LIVE WINDOW" if in_live_window(now) else "OFFLINE WINDOW"
    running = "running" if conductor_running() else "stopped"
    print(f"{state}: conductor is {running}; now={now.isoformat()}; next_transition={next_transition(now).isoformat()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start/stop MuzAIk conductor according to the 5AM-7PM ET live window.")
    parser.add_argument("command", choices=["status", "start", "stop", "ensure-window"])
    parser.add_argument("--session-id", default=os.environ.get("AIPS_RADIO_SESSION_ID", "summit-demo"))
    parser.add_argument("--section-bars", default=8, type=int)
    parser.add_argument("--prebuffer-sections", default=4, type=int)
    parser.add_argument("--max-recording-seconds", default=3600, type=int)
    parser.add_argument("--agent-mode", default=os.environ.get("AIPS_AGENT_MODE", "heuristic"), choices=["heuristic", "llm"])
    parser.add_argument("--soundfont", default=os.environ.get("SOUNDFONT_PATH"))
    args = parser.parse_args()

    if args.command == "status":
        print_status()
    elif args.command == "start":
        start_conductor(args)
    elif args.command == "stop":
        stop_conductor()
    elif args.command == "ensure-window":
        if in_live_window():
            start_conductor(args)
        else:
            stop_conductor()
        print_status()


if __name__ == "__main__":
    main()
