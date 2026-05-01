#!/usr/bin/env python3
"""Verify that an HLS playlist advances at live-ish wall-clock speed."""

from __future__ import annotations

import argparse
import re
import time
from argparse import Namespace
from pathlib import Path
from typing import cast


def read_sequence(playlist: Path) -> int:
    content = playlist.read_text()
    match = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", content)
    if not match:
        raise AssertionError(f"No media sequence in {playlist}")
    if "#EXT-X-ENDLIST" in content:
        raise AssertionError("Playlist contains #EXT-X-ENDLIST; expected live-style playlist")
    if "#EXT-X-PLAYLIST-TYPE:VOD" in content:
        raise AssertionError("Playlist is VOD; expected live-style playlist")
    return int(match.group(1))


def wait_for_playlist(playlist: Path, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if playlist.exists():
            return
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {playlist}")


def main() -> None:
    parser = argparse.ArgumentParser(description="QA a rolling HLS playlist.")
    _ = parser.add_argument("playlist", type=str)
    _ = parser.add_argument("--sample-gap-seconds", type=float, default=6.0)
    _ = parser.add_argument("--startup-timeout-seconds", type=float, default=15.0)
    _ = parser.add_argument("--min-start-sequence", type=int, default=0)
    args: Namespace = parser.parse_args()

    playlist = Path(cast(str, args.playlist))
    wait_for_playlist(playlist, cast(float, args.startup_timeout_seconds))
    deadline = time.time() + cast(float, args.startup_timeout_seconds)
    while read_sequence(playlist) < cast(int, args.min_start_sequence):
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for media sequence >= {cast(int, args.min_start_sequence)}")
        time.sleep(0.5)
    first = read_sequence(playlist)
    time.sleep(cast(float, args.sample_gap_seconds))
    second = read_sequence(playlist)
    delta = second - first
    print(f"sample1={first}")
    print(f"sample2={second}")
    print(f"delta={delta}")
    if not 0 <= delta <= 3:
        raise AssertionError(f"Expected media sequence to advance live-ish by 0-3 segments; got {delta}")


if __name__ == "__main__":
    main()
