#!/usr/bin/env python3
"""Generate a section-by-section live stream that reacts to live-control prompts."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import generate_dummy_stream as dummy
import radio_state
import role_agents


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ARCHIVE_ROOT = Path(os.environ.get("AIPS_ARCHIVE_DIR", PUBLIC / "archive"))
SESSIONS_ROOT = Path(os.environ.get("AIPS_SESSIONS_DIR", PUBLIC / "sessions"))


def archive_conductor_session(
    session_dir: Path,
    session_id: str,
    sections: list[SectionEntry],
    live_control: dummy.LiveControl,
) -> dummy.ArchiveEntry | None:
    """Archive the current conductor session as a browsable archive entry."""
    if not sections:
        return None
    recording_path = session_dir / "current-stream.mp3"
    if not recording_path.exists():
        return None
    midi_path = STREAM_DIR / "ensemble.mid"
    wav_path = STREAM_DIR / (sections[-1]["id"] + ".wav")
    state_path = STREAM_DIR / "state.json"
    bundles_path = STREAM_DIR / "role-bundles.json"

    created_at = utc_now()
    run_id = created_at.replace(":", "").replace("-", "").replace("Z", "").replace("T", "T")
    run_dir = ARCHIVE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    import shutil as _shutil
    for src, dst in [
        (recording_path, run_dir / "recording.mp3"),
        (midi_path, run_dir / "ensemble.mid"),
        (state_path, run_dir / "state.json"),
        (bundles_path, run_dir / "role-bundles.json"),
    ]:
        if src.exists():
            _shutil.copy2(src, dst)
    if wav_path.exists():
        _shutil.copy2(wav_path, run_dir / "ensemble.wav")

    tempo_bpm = dummy.effective_tempo_bpm(live_control)
    key = dummy.effective_key(live_control)
    prompt = live_control["prompt"][:80]
    entry: dummy.ArchiveEntry = {
        "id": run_id,
        "created_at": created_at,
        "title": f"Conductor session {session_id} · {prompt}",
        "recording": f"/public/archive/{run_id}/recording.mp3",
        "midi": f"/public/archive/{run_id}/ensemble.mid",
        "wav": f"/public/archive/{run_id}/ensemble.wav",
        "state": f"/public/archive/{run_id}/state.json",
        "role_bundles": f"/public/archive/{run_id}/role-bundles.json",
        "tempo_bpm": tempo_bpm,
        "key": key,
        "roles": ["bass", "lead", "percussion", "piano", "texture"],
        "prompt": live_control["prompt"],
        "style_config": live_control,
        "vote_snapshot": radio_state.vote_tally(radio_state.read_vote_round(ROOT)),
    }

    index_path = ARCHIVE_ROOT / "index.json"
    if index_path.exists():
        archive_index = json.loads(index_path.read_text())
        if not isinstance(archive_index, list):
            archive_index = []
    else:
        archive_index = []
    archive_index.insert(0, entry)
    write_json(index_path, archive_index)
    return entry
STREAM_DIR = PUBLIC / "stream"
stop_requested = False


def request_stop(signum: int, frame: object) -> None:
    global stop_requested
    _ = signum
    _ = frame
    stop_requested = True


class SectionEntry(TypedDict):
    index: int
    id: str
    created_at: str
    prompt: str
    live_control_updated_at: str
    psychosis_level: float
    seed: int
    duration_seconds: float
    segment: str
    mp3: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    _ = temp_path.write_text(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


def render_transport_stream(wav_path: Path, segment_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")
    duration = probe_duration_seconds(wav_path)
    fade_out_start = max(0.0, duration - 0.45)
    _ = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(wav_path),
            "-af",
            f"afade=t=in:st=0:d=0.08,afade=t=out:st={fade_out_start:.3f}:d=0.45",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "mpegts",
            str(segment_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def probe_duration_seconds(media_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe was not found on PATH")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def write_playlist(sections: list[SectionEntry], playlist_path: Path, list_size: int) -> None:
    visible_sections = [
        section
        for section in sections[-list_size:]
        if (ROOT / section["segment"].lstrip("/")).exists()
    ]
    media_sequence = visible_sections[0]["index"] if visible_sections else 0
    target_duration = max(1, math.ceil(max((section["duration_seconds"] for section in visible_sections), default=1.0)))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
    ]
    for section in visible_sections:
        lines.append(f"#EXTINF:{section['duration_seconds']:.6f},")
        lines.append(Path(section["segment"]).name)
    _ = playlist_path.write_text("\n".join(lines) + "\n")


def concatenate_mp3(session_dir: Path, sections: list[SectionEntry], session_id: str) -> str | None:
    if not sections:
        return None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")
    concat_path = session_dir / "concat.txt"
    output_path = session_dir / "current-stream.mp3"
    temp_path = session_dir / "current-stream.tmp.mp3"
    concat_lines = [f"file '{(ROOT / section['mp3'].lstrip('/')).resolve().as_posix()}'" for section in sections]
    _ = concat_path.write_text("\n".join(concat_lines) + "\n")
    _ = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(temp_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    temp_path.replace(output_path)
    return f"/public/sessions/{session_id}/current-stream.mp3"


def write_current_session(session_dir: Path, session_id: str, sections: list[SectionEntry], chunk_seconds: int, max_recording_seconds: int) -> None:
    recording = concatenate_mp3(session_dir, sections, session_id)
    payload = {
        "id": session_id,
        "created_at": sections[0]["created_at"] if sections else utc_now(),
        "updated_at": utc_now(),
        "title": f"Current stream session {session_id}",
        "chunk_seconds": chunk_seconds,
        "max_recording_seconds": max_recording_seconds,
        "duration_seconds": sum(section["duration_seconds"] for section in sections),
        "recording": recording,
        "chunks": [
            {
                "id": section["id"],
                "created_at": section["created_at"],
                "recording": section["mp3"],
                "title": f"Section {section['index']} · {section['prompt'][:80]}",
            }
            for section in reversed(sections)
        ],
    }
    write_json(session_dir / "index.json", payload)
    write_json(PUBLIC / "current-session.json", payload)
    if session_dir.parent != PUBLIC / "sessions":
        public_session_dir = PUBLIC / "sessions" / session_id
        public_session_dir.mkdir(parents=True, exist_ok=True)
        write_json(public_session_dir / "index.json", payload)


def delete_section_files(section: SectionEntry) -> None:
    for public_path in [section["mp3"], section["segment"]]:
        path = ROOT / public_path.lstrip("/")
        if path.exists():
            path.unlink()
    wav_path = STREAM_DIR / f"{section['id']}.wav"
    if wav_path.exists():
        wav_path.unlink()


def trim_sections(sections: list[SectionEntry], max_recording_seconds: int) -> list[SectionEntry]:
    if max_recording_seconds <= 0:
        return sections
    retained = list(sections)
    while len(retained) > 1 and sum(section["duration_seconds"] for section in retained) > max_recording_seconds:
        removed = retained.pop(0)
        delete_section_files(removed)
    return retained


def write_conductor_status(
    status: str,
    session_id: str,
    section_index: int,
    section_seconds: float,
    live_control: dummy.LiveControl,
    next_section_at: float,
    last_applied_prompt: str | None,
    agent_mode: str,
    llm_status: role_agents.LlmRuntimeStatus | None = None,
    prebuffer_sections: int = 0,
    buffered_sections: int = 0,
    live_ready: bool = False,
    prompt_sections_until_heard: int | None = None,
) -> None:
    eta = max(0, int(round(next_section_at - time.time())))
    payload = {
        "status": status,
        "session_id": session_id,
        "section_index": section_index,
        "section_seconds": section_seconds,
        "current_prompt": live_control["prompt"],
        "last_applied_prompt": last_applied_prompt,
        "psychosis_level": live_control["psychosis_level"],
        "tempo_bpm": dummy.effective_tempo_bpm(live_control),
        "key": dummy.effective_key(live_control),
        "updated_at": utc_now(),
        "next_section_at_epoch": next_section_at,
        "next_section_eta_seconds": eta,
        "delivery_status": "segment_conductor_running" if status != "stopped" else "segment_conductor_stopped",
        "agent_mode": agent_mode,
        "llm_status": llm_status,
        "prebuffer_sections": prebuffer_sections,
        "buffered_sections": buffered_sections,
        "sections_until_live": 0 if live_ready else max(0, prebuffer_sections - buffered_sections),
        "live_ready": live_ready,
        "prompt_sections_until_heard": prompt_sections_until_heard,
    }
    write_json(PUBLIC / "conductor-status.json", payload)


def playback_consumed_count(sections: list[SectionEntry], section_seconds: float, live_started_at: float | None) -> int:
    if live_started_at is None:
        return 0
    elapsed_sections = int(max(0.0, time.time() - live_started_at) // max(1.0, section_seconds))
    return min(len(sections), elapsed_sections)


def buffered_sections_available(sections: list[SectionEntry], section_seconds: float, live_started_at: float | None) -> int:
    return max(0, len(sections) - playback_consumed_count(sections, section_seconds, live_started_at))


def status_buffer_count(sections: list[SectionEntry], section_seconds: float, live_started_at: float | None, playlist_size: int) -> int:
    if live_started_at is not None:
        return min(len(sections), playlist_size)
    return buffered_sections_available(sections, section_seconds, live_started_at)


def sections_until_prompt_heard(sections: list[SectionEntry], live_control: dummy.LiveControl, section_seconds: float, live_started_at: float | None) -> int | None:
    consumed_count = playback_consumed_count(sections, section_seconds, live_started_at)
    for index, section in enumerate(sections[consumed_count:]):
        if section["prompt"] == live_control["prompt"] and section["live_control_updated_at"] == live_control["updated_at"]:
            return index
    return None


def clean_stream_dir() -> None:
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in ["segment_*.ts", "section_*.wav", "section_*.mp3"]:
        for old_path in STREAM_DIR.glob(pattern):
            old_path.unlink()
    playlist_path = STREAM_DIR / "index.m3u8"
    if playlist_path.exists():
        playlist_path.unlink()


def apply_vote_winner_to_live_control(live_control: dummy.LiveControl) -> dummy.LiveControl:
    override_path = radio_state.paths(ROOT)["state_dir"] / "admin-override.json"
    if override_path.exists():
        override = json.loads(override_path.read_text())
        if isinstance(override, dict) and override.get("enabled") is True:
            for key in ["prompt", "tempo_bpm", "key", "psychosis_level", "time_signature", "updated_at"]:
                value = override.get(key)
                if value is not None:
                    live_control[key] = value
            live_control["next_effect"] = "admin override applied at section boundary"
            return live_control
    winner = radio_state.current_winning_option(ROOT)
    if winner is None:
        return live_control
    winner_id = winner.get("id")
    if isinstance(winner_id, str) and winner_id.strip():
        live_control["active_preset"] = winner_id.strip()
    prompt = winner.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        live_control["prompt"] = prompt.strip()
    tempo_bpm = winner.get("tempo_bpm")
    if isinstance(tempo_bpm, int | float):
        live_control["tempo_bpm"] = int(dummy.clamp(int(tempo_bpm), 60, 220))
    key = winner.get("key")
    if isinstance(key, str) and key.strip():
        live_control["key"] = key.strip()
    psychosis = winner.get("psychosis_level")
    if isinstance(psychosis, int | float):
        live_control["psychosis_level"] = dummy.clamp(float(psychosis), 0.0, 1.0)
    time_signature = winner.get("time_signature")
    if isinstance(time_signature, str) and time_signature in dummy.METER_PRESETS:
        live_control["time_signature"] = time_signature
    role_winners = winner.get("role_winners")
    if isinstance(role_winners, dict):
        generation_params = live_control.get("generation_params")
        if not isinstance(generation_params, dict):
            generation_params = cast(dummy.GenerationParams, cast(object, {}))
        instrument_preferences = generation_params.get("instrument_preferences")
        if not isinstance(instrument_preferences, dict):
            instrument_preferences = {}
        for role, value in role_winners.items():
            if role in dummy.INSTRUMENT_POOLS and isinstance(value, str):
                instrument_preferences[role] = value
        generation_params["instrument_preferences"] = cast(dict[str, str], instrument_preferences)
        live_control["generation_params"] = generation_params
    live_control["updated_at"] = str(winner.get("updated_at") or live_control["updated_at"])
    live_control["next_effect"] = "winning vote applied at section boundary"
    return live_control


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    parser = argparse.ArgumentParser(description="Run a section-by-section AI ensemble conductor.")
    _ = parser.add_argument("--session-id", default="summit-demo")
    _ = parser.add_argument("--section-bars", default=8, type=int)
    _ = parser.add_argument("--max-sections", default=0, type=int, help="0 means run forever")
    _ = parser.add_argument(
        "--prebuffer-sections",
        default=4,
        type=int,
        help="Generate this many sections before publishing the live HLS playlist. Use 0 to start immediately.",
    )
    _ = parser.add_argument(
        "--max-recording-seconds",
        default=3600,
        type=int,
        help="Maximum duration retained in current-stream.mp3. Default is one hour. Use 0 to disable trimming.",
    )
    _ = parser.add_argument("--playlist-size", default=12, type=int)
    _ = parser.add_argument("--seed", default=10_000, type=int)
    _ = parser.add_argument(
        "--soundfont",
        default=None,
        type=str,
        help="Optional .sf2/.sf3 soundfont path. Requires fluidsynth; otherwise the internal synth is used.",
    )
    _ = parser.add_argument(
        "--agent-mode",
        default="heuristic",
        choices=["heuristic", "llm"],
        help="heuristic keeps the demo offline; llm uses an OpenAI-compatible chat API if OPENAI_API_KEY is set, with heuristic fallback.",
    )
    args = parser.parse_args()

    session_id = cast(str, args.session_id)
    section_bars = cast(int, args.section_bars)
    max_sections = cast(int, args.max_sections)
    prebuffer_sections = max(0, cast(int, args.prebuffer_sections))
    max_recording_seconds = cast(int, args.max_recording_seconds)
    playlist_size = cast(int, args.playlist_size)
    base_seed = cast(int, args.seed)
    agent_mode = cast(str, args.agent_mode)
    soundfont_path = cast(str | None, args.soundfont)
    section_seconds = section_bars * dummy.BEATS_PER_BAR * dummy.SECONDS_PER_BEAT
    session_dir = SESSIONS_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    clean_stream_dir()

    sections: list[SectionEntry] = []
    last_applied_prompt: str | None = None
    last_llm_status: role_agents.LlmRuntimeStatus | None = None
    last_params_status: role_agents.LlmRuntimeStatus | None = None
    live_started_at: float | None = None
    section_index = 0
    print(f"Segment conductor running at {section_bars} bars / {section_seconds:.1f}s per section")

    while not stop_requested and (max_sections <= 0 or section_index < max_sections):
        live_control = dummy.read_live_control(PUBLIC)
        preset_modes = dummy.read_preset_modes(PUBLIC)
        dummy.apply_preset_modes_to_live_control(live_control, preset_modes)
        apply_vote_winner_to_live_control(live_control)
        effective_tempo = dummy.apply_live_control_tempo(live_control)
        dummy.apply_live_control_meter(live_control)
        section_seconds = section_bars * dummy.BEATS_PER_BAR * dummy.SECONDS_PER_BEAT
        next_section_at = time.time() + section_seconds
        buffered_count = status_buffer_count(sections, section_seconds, live_started_at, playlist_size)
        live_ready = live_started_at is not None
        prompt_eta = sections_until_prompt_heard(sections, live_control, section_seconds, live_started_at)
        status_name = "generating" if live_ready else "prebuffering"
        write_conductor_status(
            status_name,
            session_id,
            section_index,
            section_seconds,
            live_control,
            next_section_at,
            last_applied_prompt,
            agent_mode,
            last_llm_status,
            prebuffer_sections,
            buffered_count,
            live_ready,
            prompt_eta,
        )

        dummy.TOTAL_BARS = section_bars
        seed = base_seed + section_index * 997
        personas = dummy.read_personas(PUBLIC)
        conductor_state = role_agents.build_conductor_state(section_index, section_bars, live_control, personas, preset_modes)
        generation_params, last_params_status = role_agents.plan_generation_params_with_status(conductor_state, live_control, agent_mode)
        if generation_params is not None:
            live_control["generation_params"] = generation_params
            conductor_state["generation_params"] = generation_params
        role_bundles, last_llm_status = role_agents.generate_role_bundles_with_status(conductor_state, seed, live_control, agent_mode)
        events = role_agents.flatten_and_validate_bundles(role_bundles, section_bars)
        section_id = f"section_{section_index:05d}"
        wav_path = STREAM_DIR / f"{section_id}.wav"
        midi_path = STREAM_DIR / "ensemble.mid"
        mp3_path = STREAM_DIR / f"{section_id}.mp3"
        ts_path = STREAM_DIR / f"segment_{section_index:05d}.ts"
        state_path = STREAM_DIR / "state.json"
        bundles_path = STREAM_DIR / "role-bundles.json"

        dummy.write_midi(events, midi_path, live_control)
        midi_events = dummy.parse_generated_midi(midi_path)
        render_engine = dummy.render_audio(midi_events, midi_path, wav_path, soundfont_path, live_control)
        dummy.create_recording(wav_path, mp3_path)
        render_transport_stream(wav_path, ts_path)
        actual_duration_seconds = probe_duration_seconds(mp3_path)
        dummy.write_manifest(midi_events, state_path, seed, live_control, render_engine)
        write_json(
            bundles_path,
            {
                "conductor_state": conductor_state,
                "preset_modes": preset_modes,
                "agent_mode": agent_mode,
                "render_engine": render_engine,
                "llm_status": last_llm_status,
                "generation_params_status": last_params_status,
                "generation_params": live_control.get("generation_params"),
                "seed": seed,
                "bundles": role_bundles,
            },
        )

        created_at = utc_now()
        sections.append(
            {
                "index": section_index,
                "id": section_id,
                "created_at": created_at,
                "prompt": live_control["prompt"],
                "live_control_updated_at": live_control["updated_at"],
                "psychosis_level": live_control["psychosis_level"],
                "seed": seed,
                "duration_seconds": actual_duration_seconds,
                "segment": f"/public/stream/{ts_path.name}",
                "mp3": f"/public/stream/{mp3_path.name}",
            }
        )
        sections = trim_sections(sections, max_recording_seconds)
        if live_started_at is None and len(sections) >= max(1, prebuffer_sections):
            live_started_at = time.time()
        live_ready = live_started_at is not None
        buffered_count = status_buffer_count(sections, section_seconds, live_started_at, playlist_size)
        if live_ready:
            write_playlist(sections, STREAM_DIR / "index.m3u8", playlist_size)
        write_current_session(session_dir, session_id, sections, int(section_seconds), max_recording_seconds)
        last_applied_prompt = live_control["prompt"]
        prompt_eta = sections_until_prompt_heard(sections, live_control, section_seconds, live_started_at)
        write_conductor_status(
            "waiting" if live_ready else "prebuffering",
            session_id,
            section_index + 1,
            section_seconds,
            live_control,
            next_section_at,
            last_applied_prompt,
            agent_mode,
            last_llm_status,
            prebuffer_sections,
            buffered_count,
            live_ready,
            prompt_eta,
        )
        print(f"Published section {section_index} · {effective_tempo} bpm · {dummy.effective_key(live_control)} · prompt: {last_applied_prompt}")

        if section_index > 0 and section_index % 50 == 0:
            entry = archive_conductor_session(session_dir, session_id, sections, live_control)
            if entry:
                print(f"Auto-archived conductor session: {entry['id']}")

        sleep_seconds = next_section_at - time.time()
        if live_ready and buffered_count > prebuffer_sections and sleep_seconds > 0:
            while sleep_seconds > 0 and not stop_requested:
                nap = min(1.0, sleep_seconds)
                time.sleep(nap)
                sleep_seconds = next_section_at - time.time()
        section_index += 1

    final_control = dummy.read_live_control(PUBLIC)
    dummy.apply_preset_modes_to_live_control(final_control, dummy.read_preset_modes(PUBLIC))
    dummy.apply_live_control_tempo(final_control)
    dummy.apply_live_control_meter(final_control)
    section_seconds = section_bars * dummy.BEATS_PER_BAR * dummy.SECONDS_PER_BEAT
    write_conductor_status(
        "stopped",
        session_id,
        section_index,
        section_seconds,
        final_control,
        time.time(),
        last_applied_prompt,
        agent_mode,
        last_llm_status,
        prebuffer_sections,
        status_buffer_count(sections, section_seconds, live_started_at, playlist_size),
        live_started_at is not None,
        sections_until_prompt_heard(sections, final_control, section_seconds, live_started_at),
    )

    entry = archive_conductor_session(session_dir, session_id, sections, final_control)
    if entry:
        print(f"Archived conductor session on shutdown: {entry['id']}")


if __name__ == "__main__":
    main()
