#!/usr/bin/env python3
"""Generate a Day 1 dummy AI ensemble stream.

This script creates deterministic symbolic events for five ensemble roles,
writes a simple MIDI file, reads that MIDI file back into events, synthesizes a
WAV preview from the MIDI-derived events with the Python standard library, and
uses FFmpeg to create rolling live-style HLS files for browser playback.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import threading
import wave
from argparse import Namespace
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RATE = 44_100
TEMPO_BPM = 92
BEATS_PER_BAR = 4
TIME_SIGNATURE = "4/4"
TOTAL_BARS = 128
SECONDS_PER_BEAT = 60 / TEMPO_BPM
ROOT_MIDI = 57  # A3
TICKS_PER_BEAT = 480
ACTIVE_PRESET = "none"
MIN_TEMPO_BPM = 60
MAX_TEMPO_BPM = 220
METER_PRESETS = {
    "4/4": {"beats_per_bar": 4, "denominator": 4, "public_safe": True},
    "3/4": {"beats_per_bar": 3, "denominator": 4, "public_safe": True},
    "6/8": {"beats_per_bar": 6, "denominator": 8, "public_safe": True},
    "5/4": {"beats_per_bar": 5, "denominator": 4, "public_safe": False},
    "7/8": {"beats_per_bar": 7, "denominator": 8, "public_safe": False},
}

PRESET_ARRANGEMENTS = {
    "none": {
        "chords": [[7, 12, 16], [5, 9, 14], [3, 7, 12], [2, 7, 11]],
        "bass": [-12, -10, -8, -7],
        "lead_shapes": [[0, 2, 4, 7], [7, 4, 2, 0], [0, 3, 5, 8], [4, 7, 9, 7]],
        "texture": [24, 28, 31],
        "density": 1.0,
    },
    "sewerslvt": {
        "chords": [[0, 3, 10], [1, 5, 8], [-2, 3, 7], [0, 6, 10]],
        "bass": [-24, -17, -22, -19],
        "lead_shapes": [[12, 10, 7, 3], [0, 1, 7, 10], [15, 12, 10, 7], [3, 6, 10, 13]],
        "texture": [19, 24, 31, 36],
        "density": 1.22,
    },
    "bladee": {
        "chords": [[0, 7, 14], [2, 9, 16], [-2, 5, 12], [4, 11, 18]],
        "bass": [-24, -12, -19, -17],
        "lead_shapes": [[7, 9, 7, 4], [0, 4, 7, 11], [12, 11, 7, 4], [2, 7, 9, 14]],
        "texture": [24, 31, 38],
        "density": 0.78,
    },
    "clairo": {
        "chords": [[0, 4, 11], [5, 9, 16], [-3, 4, 9], [2, 7, 11]],
        "bass": [-12, -7, -5, -10],
        "lead_shapes": [[0, 2, 4, 2], [7, 9, 7, 4], [4, 5, 7, 9], [2, 0, -3, 0]],
        "texture": [19, 24, 28],
        "density": 0.62,
    },
    "thundercat": {
        "chords": [[0, 3, 10, 14], [5, 9, 14, 17], [-2, 3, 8, 12], [7, 10, 15, 19]],
        "bass": [-12, -5, -10, -1],
        "lead_shapes": [[0, 3, 7, 10], [12, 10, 7, 3], [5, 8, 12, 15], [7, 11, 14, 17]],
        "texture": [24, 29, 34, 41],
        "density": 1.08,
    },
    "death_grips": {
        "chords": [[0, 1, 6], [0, 6, 10], [-1, 5, 6], [0, 3, 6]],
        "bass": [-24, -24, -18, -25],
        "lead_shapes": [[0, 6, 1, 12], [12, 6, 0, -1], [3, 6, 10, 6], [0, -1, 6, 5]],
        "texture": [12, 18, 25, 30],
        "density": 1.15,
    },
    "blood-orange": {
        "chords": [[0, 3, 10, 14], [5, 8, 12, 17], [-2, 3, 7, 10], [7, 10, 14, 19]],
        "bass": [-12, -8, -5, -10],
        "lead_shapes": [[0, 2, 3, 7], [10, 7, 5, 3], [3, 7, 10, 12], [7, 5, 3, 0]],
        "texture": [22, 27, 34],
        "density": 0.82,
    },
    "goblin": {
        "chords": [[0, 3, 6, 10], [1, 5, 8], [-2, 3, 6], [0, 5, 11]],
        "bass": [-24, -12, -23, -17],
        "lead_shapes": [[0, 3, 6, 10], [10, 6, 3, 1], [12, 11, 6, 3], [0, -2, 3, 6]],
        "texture": [18, 24, 30, 37],
        "density": 1.28,
    },
}

MIDI_PROGRAM_PRESETS = {
    "none": {"bass": 33, "piano": 4, "lead": 65, "texture": 89},
    "sewerslvt": {"bass": 38, "piano": 103, "lead": 82, "texture": 95},
    "bladee": {"bass": 39, "piano": 98, "lead": 81, "texture": 92},
    "clairo": {"bass": 34, "piano": 5, "lead": 74, "texture": 89},
    "thundercat": {"bass": 36, "piano": 6, "lead": 66, "texture": 91},
    "death_grips": {"bass": 39, "piano": 55, "lead": 87, "texture": 122},
    "blood-orange": {"bass": 34, "piano": 5, "lead": 66, "texture": 90},
    "goblin": {"bass": 38, "piano": 12, "lead": 71, "texture": 102},
}

INSTRUMENT_POOLS = {
    "percussion": [
        {"id": "standard-kit", "label": "Standard Kit", "program": 0, "bank": 128, "pack": "general-midi"},
        {"id": "room-kit", "label": "Room Kit", "program": 8, "bank": 128, "pack": "general-midi"},
        {"id": "power-kit", "label": "Power Kit", "program": 16, "bank": 128, "pack": "general-midi"},
        {"id": "jazz-kit", "label": "Jazz Kit", "program": 32, "bank": 128, "pack": "general-midi"},
    ],
    "bass": [
        {"id": "upright", "label": "Acoustic Bass", "program": 32, "bank": 0, "pack": "general-midi"},
        {"id": "finger", "label": "Electric Bass (finger)", "program": 33, "bank": 0, "pack": "general-midi"},
        {"id": "picked", "label": "Electric Bass (picked)", "program": 34, "bank": 0, "pack": "general-midi"},
        {"id": "fretless", "label": "Fretless Bass", "program": 35, "bank": 0, "pack": "general-midi"},
        {"id": "synth-sub", "label": "Synth Bass", "program": 38, "bank": 0, "pack": "general-midi"},
    ],
    "piano": [
        {"id": "grand", "label": "Acoustic Grand", "program": 0, "bank": 0, "pack": "general-midi"},
        {"id": "rhodes", "label": "Electric Piano", "program": 4, "bank": 0, "pack": "general-midi"},
        {"id": "organ", "label": "Drawbar Organ", "program": 16, "bank": 0, "pack": "general-midi"},
        {"id": "nylon-guitar", "label": "Nylon Guitar", "program": 24, "bank": 0, "pack": "general-midi"},
        {"id": "mallet", "label": "Vibraphone", "program": 11, "bank": 0, "pack": "general-midi"},
    ],
    "lead": [
        {"id": "trumpet", "label": "Trumpet", "program": 56, "bank": 0, "pack": "general-midi"},
        {"id": "alto-sax", "label": "Alto Sax", "program": 65, "bank": 0, "pack": "general-midi"},
        {"id": "flute", "label": "Flute", "program": 73, "bank": 0, "pack": "general-midi"},
        {"id": "violin", "label": "Violin", "program": 40, "bank": 0, "pack": "general-midi"},
        {"id": "square", "label": "Square Lead", "program": 80, "bank": 0, "pack": "general-midi"},
        {"id": "saw", "label": "Saw Lead", "program": 81, "bank": 0, "pack": "general-midi"},
    ],
    "texture": [
        {"id": "new-age-pad", "label": "New Age Pad", "program": 88, "bank": 0, "pack": "general-midi"},
        {"id": "warm-pad", "label": "Warm Pad", "program": 89, "bank": 0, "pack": "general-midi"},
        {"id": "choir-pad", "label": "Choir Pad", "program": 91, "bank": 0, "pack": "general-midi"},
        {"id": "halo-pad", "label": "Halo Pad", "program": 94, "bank": 0, "pack": "general-midi"},
        {"id": "crystal", "label": "Crystal", "program": 98, "bank": 0, "pack": "general-midi"},
    ],
}

SOUNDFONT_PACKS = {
    "general-midi": {
        "label": "MuseScore General / FluidR3-compatible General MIDI",
        "license": "MIT-compatible General MIDI soundfont required for deployment",
        "source_url": "https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/",
        "caveat": "Default deploy-safe target; install on Hetzner and keep license file nearby.",
    },
    "generaluser-gs": {
        "label": "GeneralUser GS",
        "license": "Custom permissive; conditional",
        "source_url": "https://github.com/mrbumpy409/GeneralUser-GS",
        "caveat": "Optional only after documenting sample-provenance caveats in README/archive metadata.",
    },
    "vsco2-ce": {
        "label": "VSCO2 Community Edition",
        "license": "CC0; deferred",
        "source_url": "https://github.com/sgossner/VSCO-2-CE",
        "caveat": "Deferred unless a clean SF2/SF3 conversion and license file are added explicitly.",
    },
}

PRESET_PERFORMANCE_BEHAVIOR = {
    "none": {
        "piano_beats": [1.0, 3.0],
        "piano_duration": (1.1, 1.9),
        "piano_probability": 0.82,
        "lead_bar_mods": [1, 2],
        "lead_step": 0.75,
        "lead_duration": (0.34, 0.50),
        "lead_register_offsets": [0, 0, 0, 12],
        "lead_probability": 0.86,
        "lead_velocity": (54, 16),
    },
    "sewerslvt": {
        "piano_beats": [1.0, 1.75, 3.0, 3.75],
        "piano_duration": (0.25, 0.65),
        "piano_probability": 0.66,
        "lead_bar_mods": [1, 2, 3],
        "lead_step": 0.5,
        "lead_duration": (0.18, 0.34),
        "lead_register_offsets": [12, 12, 24],
        "lead_probability": 0.92,
        "lead_velocity": (62, 22),
    },
    "bladee": {
        "piano_beats": [1.0, 2.5],
        "piano_duration": (1.8, 3.2),
        "piano_probability": 0.46,
        "lead_bar_mods": [1, 3],
        "lead_step": 1.0,
        "lead_duration": (0.55, 1.1),
        "lead_register_offsets": [12, 12, 24],
        "lead_probability": 0.58,
        "lead_velocity": (45, 12),
    },
    "clairo": {
        "piano_beats": [1.0, 2.75, 4.0],
        "piano_duration": (0.7, 1.45),
        "piano_probability": 0.52,
        "lead_bar_mods": [2, 4],
        "lead_step": 0.9,
        "lead_duration": (0.45, 0.95),
        "lead_register_offsets": [0, 0, 12],
        "lead_probability": 0.52,
        "lead_velocity": (44, 13),
    },
    "thundercat": {
        "piano_beats": [1.0, 1.5, 2.75, 3.5],
        "piano_duration": (0.28, 0.95),
        "piano_probability": 0.74,
        "lead_bar_mods": [1, 2, 3, 4],
        "lead_step": 0.5,
        "lead_duration": (0.22, 0.55),
        "lead_register_offsets": [0, 12, 12, 24],
        "lead_probability": 0.78,
        "lead_velocity": (58, 18),
    },
    "death_grips": {
        "piano_beats": [1.0, 1.25, 2.0, 3.5],
        "piano_duration": (0.12, 0.42),
        "piano_probability": 0.72,
        "lead_bar_mods": [1, 2, 4],
        "lead_step": 0.5,
        "lead_duration": (0.12, 0.38),
        "lead_register_offsets": [0, 12, 24],
        "lead_probability": 0.82,
        "lead_velocity": (66, 24),
    },
    "blood-orange": {
        "piano_beats": [1.0, 2.25, 3.0, 4.0],
        "piano_duration": (0.45, 1.3),
        "piano_probability": 0.62,
        "lead_bar_mods": [1, 3, 4],
        "lead_step": 0.75,
        "lead_duration": (0.38, 0.85),
        "lead_register_offsets": [0, 12, 12],
        "lead_probability": 0.62,
        "lead_velocity": (50, 14),
    },
    "goblin": {
        "piano_beats": [1.0, 1.5, 2.25, 3.25, 4.25],
        "piano_duration": (0.14, 0.55),
        "piano_probability": 0.78,
        "lead_bar_mods": [1, 2, 3, 4],
        "lead_step": 0.375,
        "lead_duration": (0.12, 0.34),
        "lead_register_offsets": [0, 12, 24, 24],
        "lead_probability": 0.88,
        "lead_velocity": (62, 22),
    },
}


@dataclass(frozen=True)
class Event:
    role: str
    bar: int
    beat: float
    duration_beats: float
    pitch: int
    velocity: int

    @property
    def start_seconds(self) -> float:
        beats = (self.bar - 1) * BEATS_PER_BAR + (self.beat - 1)
        return beats * SECONDS_PER_BEAT

    @property
    def duration_seconds(self) -> float:
        return self.duration_beats * SECONDS_PER_BEAT


class EventJson(TypedDict):
    role: str
    bar: int
    beat: float
    duration_beats: float
    pitch: int
    velocity: int


class ArchiveEntry(TypedDict):
    id: str
    created_at: str
    title: str
    recording: str
    midi: str
    wav: str
    state: str
    tempo_bpm: int
    key: str
    roles: list[str]
    role_bundles: NotRequired[str]
    prompt: NotRequired[str]
    style_config: NotRequired[object]
    vote_snapshot: NotRequired[object]
    render_engine: NotRequired[str]
    soundfont: NotRequired[object]
    time_signature: NotRequired[str]


class SessionChunk(TypedDict):
    id: str
    created_at: str
    recording: str
    title: str


class StreamSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    title: str
    chunk_seconds: int
    duration_seconds: float
    recording: str | None
    chunks: list[SessionChunk]


class WebsiteState(TypedDict):
    tempo_bpm: int
    key: str
    bars: int
    roles: list[str]
    stream: str
    status: dict[str, str]
    events: list[EventJson]
    seed: int
    live_control: "LiveControl"
    render_engine: str


class GenerationParams(TypedDict, total=False):
    source: str
    summary: str
    chords: list[list[int]]
    bass: list[int]
    lead_shapes: list[list[int]]
    texture: list[int]
    density: float
    midi_programs: dict[str, int]
    instrument_preferences: dict[str, str]


class LiveControl(TypedDict):
    prompt: str
    psychosis_level: float
    updated_at: str
    applies_to: str
    delivery_status: str
    next_section_eta_seconds: int | None
    next_effect: str
    tempo_bpm: NotRequired[int]
    key: NotRequired[str]
    active_preset: NotRequired[str]
    generation_params: NotRequired[GenerationParams]
    time_signature: NotRequired[str]


def midi_to_frequency(pitch: int) -> float:
    return 440.0 * (2 ** ((pitch - 69) / 12))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def extract_tempo_bpm(prompt: str, fallback: int = TEMPO_BPM) -> int:
    match = re.search(r"\b(\d{2,3})\s*bpm\b", prompt.lower())
    if not match:
        return fallback
    return int(clamp(int(match.group(1)), MIN_TEMPO_BPM, MAX_TEMPO_BPM))


def extract_key(prompt: str, fallback: str = "A minor") -> str:
    lowered = prompt.lower()
    note_names = {
        "c": "C", "c#": "C#", "db": "Db", "d": "D", "d#": "D#", "eb": "Eb",
        "e": "E", "f": "F", "f#": "F#", "gb": "Gb", "g": "G", "g#": "G#",
        "ab": "Ab", "a": "A", "a#": "A#", "bb": "Bb", "b": "B",
    }
    patterns = [
        r"\bkey\s*(?:of|is|:)?\s*([a-g](?:#|b)?)(?:\s|-)*(major|minor|maj|min|m)?\b",
        r"\bin\s+([a-g](?:#|b)?)(?:\s|-)*(major|minor|maj|min|m)\b",
        r"\b([a-g](?:#|b)?)(m)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        note = note_names.get(match.group(1))
        if not note:
            continue
        quality = match.group(2) if match.lastindex and match.lastindex >= 2 else "minor"
        if quality in {"minor", "min", "m"}:
            return f"{note} minor"
        if quality in {"major", "maj"}:
            return f"{note} major"
        return note
    return fallback


def effective_tempo_bpm(live_control: LiveControl) -> int:
    tempo = live_control.get("tempo_bpm")
    if isinstance(tempo, int):
        return int(clamp(tempo, MIN_TEMPO_BPM, MAX_TEMPO_BPM))
    return extract_tempo_bpm(live_control["prompt"])


def effective_key(live_control: LiveControl) -> str:
    key = live_control.get("key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return extract_key(live_control["prompt"])


def set_tempo_bpm(tempo_bpm: int) -> None:
    global TEMPO_BPM, SECONDS_PER_BEAT
    TEMPO_BPM = int(clamp(tempo_bpm, MIN_TEMPO_BPM, MAX_TEMPO_BPM))
    SECONDS_PER_BEAT = 60 / TEMPO_BPM


def effective_time_signature(live_control: LiveControl | None = None) -> str:
    if live_control is not None:
        raw_signature = live_control.get("time_signature")
        if isinstance(raw_signature, str) and raw_signature in METER_PRESETS:
            return raw_signature
    return TIME_SIGNATURE if TIME_SIGNATURE in METER_PRESETS else "4/4"


def set_time_signature(signature: str) -> str:
    global TIME_SIGNATURE, BEATS_PER_BAR
    if signature not in METER_PRESETS:
        signature = "4/4"
    TIME_SIGNATURE = signature
    BEATS_PER_BAR = int(METER_PRESETS[signature]["beats_per_bar"])
    return TIME_SIGNATURE


def apply_live_control_meter(live_control: LiveControl) -> str:
    return set_time_signature(effective_time_signature(live_control))


def apply_live_control_tempo(live_control: LiveControl) -> int:
    tempo = effective_tempo_bpm(live_control)
    set_tempo_bpm(tempo)
    return tempo


def set_active_preset(preset_id: str | None) -> str:
    global ACTIVE_PRESET
    if isinstance(preset_id, str) and preset_id in PRESET_ARRANGEMENTS:
        ACTIVE_PRESET = preset_id
    else:
        ACTIVE_PRESET = "none"
    return ACTIVE_PRESET


def active_preset_id(live_control: LiveControl | None = None) -> str:
    if live_control is not None:
        preset = live_control.get("active_preset")
        if isinstance(preset, str) and preset in PRESET_ARRANGEMENTS:
            return preset
    return ACTIVE_PRESET if ACTIVE_PRESET in PRESET_ARRANGEMENTS else "none"


def apply_preset_modes_to_live_control(live_control: LiveControl, preset_modes: dict[str, object]) -> LiveControl:
    active_profile = preset_modes.get("active_profile")
    profiles_raw = preset_modes.get("profiles")
    profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
    if isinstance(active_profile, str) and active_profile in PRESET_ARRANGEMENTS:
        live_control["active_preset"] = active_profile
        _ = set_active_preset(active_profile)
        active_profile_config = profiles.get(active_profile)
        known_profile_prompts = {
            profile.get("live_prompt")
            for profile in profiles.values()
            if isinstance(profile, dict) and isinstance(profile.get("live_prompt"), str)
        }
        if isinstance(active_profile_config, dict) and live_control["prompt"] in known_profile_prompts:
            profile_prompt = active_profile_config.get("live_prompt")
            profile_tempo = active_profile_config.get("tempo_bpm")
            profile_key = active_profile_config.get("key")
            profile_psychosis = active_profile_config.get("psychosis_level")
            if isinstance(profile_prompt, str) and profile_prompt.strip():
                live_control["prompt"] = profile_prompt.strip()
            if isinstance(profile_tempo, int | float):
                live_control["tempo_bpm"] = int(clamp(int(profile_tempo), MIN_TEMPO_BPM, MAX_TEMPO_BPM))
            if isinstance(profile_key, str) and profile_key.strip():
                live_control["key"] = profile_key.strip()
            if isinstance(profile_psychosis, int | float):
                live_control["psychosis_level"] = clamp(float(profile_psychosis), 0.0, 1.0)
    else:
        live_control["active_preset"] = "none"
        _ = set_active_preset("none")
    return live_control


def arrangement_for(live_control: LiveControl) -> dict[str, object]:
    return cast(dict[str, object], PRESET_ARRANGEMENTS.get(active_preset_id(live_control), PRESET_ARRANGEMENTS["none"]))


def root_midi_for_key(key: str) -> int:
    note_offsets = {"c": -9, "c#": -8, "db": -8, "d": -7, "d#": -6, "eb": -6, "e": -5, "f": -4, "f#": -3, "gb": -3, "g": -2, "g#": -1, "ab": -1, "a": 0, "a#": 1, "bb": 1, "b": 2}
    root = key.split()[0].lower() if key else "a"
    return ROOT_MIDI + note_offsets.get(root, 0)


def generation_instrument_preferences(live_control: LiveControl | None = None) -> dict[str, str]:
    if live_control is None:
        return {}
    generation_params = live_control.get("generation_params")
    if not isinstance(generation_params, dict):
        return {}
    raw_preferences = generation_params.get("instrument_preferences")
    if not isinstance(raw_preferences, dict):
        return {}
    return {role: value for role, value in raw_preferences.items() if isinstance(role, str) and isinstance(value, str)}


def configured_instrument_for(role: str, preferred_id: str | None = None, fallback_program: int | None = None) -> dict[str, object]:
    pool = instrument_pool_for_role(role)
    if preferred_id:
        preferred_match = next((item for item in pool if item.get("id") == preferred_id), None)
        if preferred_match is not None:
            return dict(preferred_match)
    if fallback_program is not None:
        program_match = next((item for item in pool if item.get("program") == fallback_program), None)
        if program_match is not None:
            return dict(program_match)
    if pool:
        return dict(pool[0])
    return {"id": role, "label": role.title(), "program": fallback_program or 0, "bank": 0, "pack": "general-midi"}


def midi_programs_for(live_control: LiveControl | None = None) -> dict[str, int]:
    preset_programs = dict(MIDI_PROGRAM_PRESETS.get(active_preset_id(live_control), MIDI_PROGRAM_PRESETS["none"]))
    preferences = generation_instrument_preferences(live_control)
    programs = dict(preset_programs)
    if live_control is not None:
        generation_params = live_control.get("generation_params")
        raw_programs = generation_params.get("midi_programs") if isinstance(generation_params, dict) else None
        if isinstance(raw_programs, dict):
            for role in ["bass", "piano", "lead", "texture"]:
                program = raw_programs.get(role)
                if isinstance(program, int):
                    programs[role] = int(clamp(program, 0, 127))
    for role in ["bass", "piano", "lead", "texture"]:
        instrument = configured_instrument_for(role, preferences.get(role), programs.get(role, MIDI_PROGRAM_PRESETS["none"].get(role, 0)))
        program = instrument.get("program")
        if isinstance(program, int):
            programs[role] = int(clamp(program, 0, 127))
    return programs


def instrument_pool_for_role(role: str) -> list[dict[str, object]]:
    config = read_music_config(ROOT / "public")
    raw_pools = config.get("instrument_pools") if isinstance(config, dict) else None
    pools = raw_pools if isinstance(raw_pools, dict) else INSTRUMENT_POOLS
    return [dict(item) for item in pools.get(role, []) if isinstance(item, dict)]


def read_music_config(public_root: Path) -> dict[str, object]:
    config_path = public_root / "music-config.json"
    if not config_path.exists():
        return {"instrument_pools": INSTRUMENT_POOLS, "meter_presets": METER_PRESETS, "soundfont_packs": SOUNDFONT_PACKS}
    try:
        raw_config = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        return {"instrument_pools": INSTRUMENT_POOLS, "meter_presets": METER_PRESETS, "soundfont_packs": SOUNDFONT_PACKS}
    return cast(dict[str, object], raw_config if isinstance(raw_config, dict) else {})


def selected_instruments_for(live_control: LiveControl | None = None) -> dict[str, dict[str, object]]:
    programs = midi_programs_for(live_control)
    preferences = generation_instrument_preferences(live_control)
    selected: dict[str, dict[str, object]] = {}
    for role in ["percussion", "bass", "piano", "lead", "texture"]:
        program = 0 if role == "percussion" else programs.get(role, MIDI_PROGRAM_PRESETS["none"].get(role, 0))
        selected[role] = configured_instrument_for(role, preferences.get(role), program)
    return selected


def soundfont_metadata(soundfont_path: str | None = None) -> dict[str, object]:
    resolved = soundfont_path or os.environ.get("SOUNDFONT_PATH")
    pack_id = os.environ.get("SOUNDFONT_PACK_ID", "general-midi")
    config = read_music_config(ROOT / "public")
    raw_packs = config.get("soundfont_packs") if isinstance(config, dict) else None
    packs = raw_packs if isinstance(raw_packs, dict) else SOUNDFONT_PACKS
    default_pack = packs.get("general-midi", SOUNDFONT_PACKS["general-midi"])
    selected_pack = packs.get(pack_id, default_pack)
    pack: dict[str, object] = dict(selected_pack if isinstance(selected_pack, dict) else default_pack)
    pack["id"] = pack_id
    pack["path_configured"] = bool(resolved)
    pack["path_name"] = Path(resolved).name if resolved else None
    return pack


def performance_behavior_for(live_control: LiveControl) -> dict[str, object]:
    return cast(dict[str, object], PRESET_PERFORMANCE_BEHAVIOR.get(active_preset_id(live_control), PRESET_PERFORMANCE_BEHAVIOR["none"]))


def arrangement_with_generation_params(live_control: LiveControl) -> dict[str, object]:
    arrangement = dict(arrangement_for(live_control))
    generation_params = live_control.get("generation_params")
    if not isinstance(generation_params, dict):
        return arrangement
    for key in ["chords", "lead_shapes"]:
        value = generation_params.get(key)
        if isinstance(value, list) and value and all(isinstance(row, list) for row in value):
            arrangement[key] = value
    for key in ["bass", "texture"]:
        value = generation_params.get(key)
        if isinstance(value, list) and value and all(isinstance(item, int) for item in value):
            arrangement[key] = value
    density = generation_params.get("density")
    if isinstance(density, int | float):
        arrangement["density"] = clamp(float(density), 0.2, 2.4)
    return arrangement


def read_live_control(public_root: Path) -> LiveControl:
    default_control: LiveControl = {
        "prompt": "Keep the band spacious, late-night, and coherent.",
        "psychosis_level": 0.25,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "applies_to": "next generated section",
        "delivery_status": "default_control; llm_segment_conductor_not_running_yet",
        "next_section_eta_seconds": None,
        "next_effect": "next generator run/form",
        "tempo_bpm": TEMPO_BPM,
        "key": "A minor",
        "active_preset": ACTIVE_PRESET,
        "time_signature": TIME_SIGNATURE,
    }
    control_path = public_root / "live-control.json"
    if not control_path.exists():
        return default_control
    raw_control = json.loads(control_path.read_text())
    if not isinstance(raw_control, dict):
        return default_control
    prompt = raw_control.get("prompt")
    psychosis_level = raw_control.get("psychosis_level")
    updated_at = raw_control.get("updated_at")
    applies_to = raw_control.get("applies_to")
    delivery_status = raw_control.get("delivery_status")
    next_effect = raw_control.get("next_effect")
    if not isinstance(prompt, str) or not isinstance(psychosis_level, int | float):
        return default_control
    raw_tempo = raw_control.get("tempo_bpm")
    tempo_bpm = int(clamp(int(raw_tempo), MIN_TEMPO_BPM, MAX_TEMPO_BPM)) if isinstance(raw_tempo, int | float) else extract_tempo_bpm(prompt)
    raw_key = raw_control.get("key")
    key = raw_key.strip() if isinstance(raw_key, str) and raw_key.strip() else extract_key(prompt)
    raw_active_preset = raw_control.get("active_preset")
    raw_time_signature = raw_control.get("time_signature")
    return {
        "prompt": prompt,
        "psychosis_level": clamp(float(psychosis_level), 0.0, 1.0),
        "updated_at": updated_at if isinstance(updated_at, str) else default_control["updated_at"],
        "applies_to": applies_to if isinstance(applies_to, str) else "next generated section",
        "delivery_status": delivery_status if isinstance(delivery_status, str) else "control_server_received; llm_segment_conductor_not_running_yet",
        "next_section_eta_seconds": None,
        "next_effect": next_effect if isinstance(next_effect, str) else "next generator run/form",
        "tempo_bpm": tempo_bpm,
        "key": key,
        "active_preset": raw_active_preset if isinstance(raw_active_preset, str) else ACTIVE_PRESET,
        "time_signature": raw_time_signature if isinstance(raw_time_signature, str) and raw_time_signature in METER_PRESETS else "4/4",
    }


def read_personas(public_root: Path) -> dict[str, object]:
    personas_path = public_root / "personas.json"
    if not personas_path.exists():
        return {}
    raw_personas = json.loads(personas_path.read_text())
    return cast(dict[str, object], raw_personas if isinstance(raw_personas, dict) else {})


def read_preset_modes(public_root: Path) -> dict[str, object]:
    preset_path = public_root / "preset-modes.json"
    if not preset_path.exists():
        return {}
    raw_presets = json.loads(preset_path.read_text())
    return cast(dict[str, object], raw_presets if isinstance(raw_presets, dict) else {})


def build_events(seed: int, live_control: LiveControl) -> list[Event]:
    rng = random.Random(seed)
    events: list[Event] = []
    prompt = live_control["prompt"].lower()
    psychosis_level = live_control["psychosis_level"]
    sparse = any(word in prompt for word in ["sparse", "minimal", "quiet", "space", "spacious"])
    intense = any(word in prompt for word in ["intense", "louder", "build", "energy", "driving"])
    haunted = any(word in prompt for word in ["haunted", "anxious", "lost", "psychosis", "weird", "dissonant", "unstable"])
    steady_bass = "bass" in prompt and any(word in prompt for word in ["steady", "anchor", "ground", "stable"])
    density_scale = 0.72 if sparse else 1.0
    if intense:
        density_scale += 0.18
    texture_bias = 0.22 if haunted else 0.0
    lead_bias = -0.18 if sparse else 0.0
    if "lead" in prompt or "horn" in prompt or "solo" in prompt:
        lead_bias += 0.16
    drift = clamp(psychosis_level + (0.18 if haunted else 0.0), 0.0, 1.0)
    arrangement = arrangement_with_generation_params(live_control)
    behavior = performance_behavior_for(live_control)
    root_midi = root_midi_for_key(effective_key(live_control))
    raw_arrangement_density = arrangement.get("density", 1.0)
    arrangement_density = float(raw_arrangement_density) if isinstance(raw_arrangement_density, int | float) else 1.0
    density_scale *= arrangement_density
    piano_chords = [[root_midi + int(interval) for interval in chord] for chord in cast(list[list[int]], arrangement["chords"])]
    bass_roots = [root_midi + int(interval) for interval in cast(list[int], arrangement["bass"])]
    lead_shapes = cast(list[list[int]], arrangement["lead_shapes"])
    texture_notes = [root_midi + int(interval) for interval in cast(list[int], arrangement["texture"])]

    for bar in range(1, TOTAL_BARS + 1):
        phrase = (bar - 1) // 4
        phrase_energy = clamp(0.72 + 0.24 * math.sin(phrase / 2.7) + rng.uniform(-0.08, 0.08) + (0.15 if intense else 0.0) - (0.12 if sparse else 0.0), 0.32, 1.15)
        chord_shift_options = [-2, 0, 0, 0, 2, 6 if drift > 0.55 else 0]
        chord_shift = rng.choice(chord_shift_options) if bar % 8 == 1 or rng.random() < drift * 0.08 else 0
        chord = [pitch + chord_shift for pitch in piano_chords[(bar - 1) % len(piano_chords)]]
        bass_root = bass_roots[(bar - 1) % len(bass_roots)] + chord_shift
        bass_pattern = [bass_root, bass_root + 7, bass_root + rng.choice([9, 10, 12]), bass_root + rng.choice([10, 12])]
        lead_shape = rng.choice(lead_shapes)
        lead_register_offsets = cast(list[int], behavior.get("lead_register_offsets", [0, 0, 0, 12]))
        lead_register = ROOT_MIDI + 12 + chord_shift + rng.choice(lead_register_offsets)

        beat_numbers = [float(beat) for beat in range(1, BEATS_PER_BAR + 1)]
        accent_beats = {1.0, 3.0 if BEATS_PER_BAR >= 4 else float(BEATS_PER_BAR)}
        for beat in beat_numbers:
            drum_pitch = 36 if beat in accent_beats else 42
            velocity = int(82 + phrase_energy * 20 + rng.uniform(-8, 8))
            events.append(Event("percussion", bar, beat, 0.16 + rng.uniform(0.0, 0.08), drum_pitch, velocity))
        if rng.random() < 0.72 * density_scale:
            events.append(Event("percussion", bar, min(2.5, BEATS_PER_BAR + 0.5), 0.12, 38, int(58 + phrase_energy * 18)))
        if bar % 4 == 0 or rng.random() < 0.24 * density_scale:
            events.append(Event("percussion", bar, min(BEATS_PER_BAR + 0.5, 4.5), 0.12, 38, int(62 + phrase_energy * 18)))
            if rng.random() < 0.45:
                events.append(Event("percussion", bar, min(BEATS_PER_BAR + 0.75, 4.75), 0.1, 42, 54))

        for idx, pitch in enumerate(bass_pattern[:BEATS_PER_BAR]):
            approach = 0 if steady_bass else (-1 if idx == 3 and rng.random() < 0.34 + drift * 0.12 else 0)
            bass_duration = 0.9 if steady_bass else 0.76 + rng.uniform(0.0, 0.16)
            events.append(Event("bass", bar, idx + 1.0, bass_duration, pitch + approach, int(70 + phrase_energy * 12)))

        piano_beats = cast(list[float], behavior.get("piano_beats", [1.0, 3.0]))
        piano_duration_range = cast(tuple[float, float], behavior.get("piano_duration", (1.1, 1.9)))
        raw_piano_probability = behavior.get("piano_probability", 0.82)
        piano_probability = float(raw_piano_probability) if isinstance(raw_piano_probability, int | float) else 0.82
        for beat_index, beat in enumerate(piano_beats):
            if beat > BEATS_PER_BAR:
                continue
            if beat_index > 0 and rng.random() >= clamp(piano_probability * density_scale, 0.08, 0.96):
                continue
            for pitch in chord:
                voicing = rng.choice([-12, 0, 0, 12])
                duration = rng.uniform(piano_duration_range[0], piano_duration_range[1])
                velocity = int(40 + phrase_energy * (18 if beat_index == 0 else 13))
                events.append(Event("piano", bar, beat + rng.uniform(0.0, 0.06), duration, pitch + voicing, velocity))

        lead_bar_mods = cast(list[int], behavior.get("lead_bar_mods", [1, 2]))
        raw_lead_step = behavior.get("lead_step", 0.75)
        lead_step = float(raw_lead_step) if isinstance(raw_lead_step, int | float) else 0.75
        lead_duration_range = cast(tuple[float, float], behavior.get("lead_duration", (0.34, 0.50)))
        raw_lead_probability = behavior.get("lead_probability", 0.86)
        lead_probability = float(raw_lead_probability) if isinstance(raw_lead_probability, int | float) else 0.86
        lead_velocity_base, lead_velocity_scale = cast(tuple[int, int], behavior.get("lead_velocity", (54, 16)))
        if bar % 4 in lead_bar_mods and rng.random() < clamp(lead_probability * density_scale + lead_bias, 0.16, 0.98):
            for idx, interval in enumerate(lead_shape):
                if rng.random() < clamp((0.76 + drift * 0.18) * density_scale, 0.18, 0.96):
                    altered_interval = interval + (rng.choice([-1, 0, 1]) if rng.random() < drift * 0.25 else 0)
                    start_beat = 1.0 + idx * lead_step + rng.uniform(-0.04, 0.06)
                    while start_beat > BEATS_PER_BAR + 0.85:
                        start_beat -= 2.0
                    start_beat = clamp(start_beat, 1.0, BEATS_PER_BAR + 0.85)
                    duration = rng.uniform(lead_duration_range[0], lead_duration_range[1])
                    velocity = int(lead_velocity_base + phrase_energy * lead_velocity_scale)
                    events.append(Event("lead", bar, start_beat, duration, lead_register + altered_interval, velocity))
        elif bar % 4 == 3:
            duration = rng.uniform(lead_duration_range[0], max(lead_duration_range[1], lead_duration_range[0] + 0.3))
            velocity = int(lead_velocity_base + phrase_energy * (lead_velocity_scale * 0.8))
            events.append(Event("lead", bar, 2.0 + rng.uniform(-0.08, 0.08), duration, lead_register + rng.choice([7, 9, 12]), velocity))

        if bar % 2 == 1 or rng.random() < texture_bias:
            for pitch in rng.sample(texture_notes, k=2):
                events.append(Event("texture", bar, 1.0, 7.6, pitch + chord_shift + rng.choice([-12, 0, 0]), int(24 + phrase_energy * 10)))

    return events


def role_waveform(role: str, pitch: int, frequency: float, t: float, preset_id: str = "none") -> float:
    if role == "percussion":
        if pitch == 36:
            return (math.sin(2 * math.pi * 62 * t) + 0.35 * math.sin(2 * math.pi * 124 * t)) * math.exp(-24 * t)
        if pitch == 38:
            body = math.sin(2 * math.pi * 185 * t) * math.exp(-18 * t)
            snap = math.sin(2 * math.pi * 2200 * t) * math.exp(-52 * t)
            return body + 0.35 * snap
        return math.sin(2 * math.pi * 5200 * t) * math.exp(-82 * t)
    if role == "bass":
        raw = math.sin(2 * math.pi * frequency * t) + 0.42 * math.sin(4 * math.pi * frequency * t) + 0.12 * math.sin(6 * math.pi * frequency * t)
        if preset_id in {"death_grips", "goblin", "sewerslvt"}:
            return math.tanh(raw * (2.2 if preset_id == "death_grips" else 1.55))
        if preset_id == "thundercat":
            return raw + 0.24 * math.sin(2 * math.pi * frequency * 3.01 * t) * math.sin(2 * math.pi * 3.7 * t)
        if preset_id in {"bladee", "clairo", "blood-orange"}:
            return math.sin(2 * math.pi * frequency * t) * 0.92 + 0.18 * math.sin(2 * math.pi * frequency * 2.0 * t)
        return raw
    if role == "piano":
        if preset_id == "goblin":
            return (math.sin(2 * math.pi * frequency * t) + 0.4 * math.sin(2 * math.pi * (frequency * 1.014) * t) + 0.2 * math.sin(2 * math.pi * frequency * 4.0 * t)) * math.exp(-2.8 * t)
        if preset_id == "death_grips":
            return math.tanh((math.sin(2 * math.pi * frequency * t) + math.sin(2 * math.pi * frequency * 1.5 * t)) * 1.7) * math.exp(-4.5 * t)
        if preset_id in {"clairo", "blood-orange"}:
            return (math.sin(2 * math.pi * frequency * t) + 0.22 * math.sin(2 * math.pi * frequency * 2.0 * t)) * math.exp(-1.15 * t)
        tine = math.sin(2 * math.pi * frequency * t) + 0.45 * math.sin(2 * math.pi * frequency * 2.01 * t)
        bell = 0.2 * math.sin(2 * math.pi * frequency * 3.97 * t) * math.exp(-5.5 * t)
        return tine * math.exp(-1.8 * t) + bell
    if role == "lead":
        vibrato_depth = 0.012 if preset_id in {"goblin", "death_grips"} else 0.006
        vibrato = 1 + vibrato_depth * math.sin(2 * math.pi * (6.8 if preset_id == "goblin" else 5.2) * t)
        if preset_id == "bladee":
            return (math.sin(2 * math.pi * frequency * vibrato * t) + 0.28 * math.sin(2 * math.pi * frequency * 2.0 * t)) * math.exp(-0.45 * t)
        if preset_id == "thundercat":
            return math.sin(2 * math.pi * frequency * vibrato * t) + 0.3 * math.sin(2 * math.pi * frequency * 2.0 * vibrato * t) + 0.12 * math.sin(2 * math.pi * frequency * 3.0 * t)
        return math.sin(2 * math.pi * frequency * vibrato * t) + 0.18 * math.sin(2 * math.pi * frequency * 2.0 * vibrato * t)
    if preset_id in {"sewerslvt", "bladee"}:
        return (math.sin(2 * math.pi * frequency * t) + 0.34 * math.sin(2 * math.pi * (frequency * 1.007) * t)) * 0.78
    if preset_id in {"death_grips", "goblin"}:
        return math.tanh((math.sin(2 * math.pi * frequency * t) + 0.35 * math.sin(2 * math.pi * frequency * 2.9 * t)) * 1.4) * 0.55
    return (math.sin(2 * math.pi * frequency * t) + 0.22 * math.sin(2 * math.pi * (frequency * 1.005) * t)) * 0.7


def synthesize_wav(events: list[Event], wav_path: Path, live_control: LiveControl | None = None) -> None:
    duration = TOTAL_BARS * BEATS_PER_BAR * SECONDS_PER_BEAT + 1.0
    total_samples = int(duration * SAMPLE_RATE)
    left_samples: list[float] = [0.0] * total_samples
    right_samples: list[float] = [0.0] * total_samples
    role_gain = {
        "percussion": 0.42,
        "bass": 0.24,
        "piano": 0.15,
        "lead": 0.16,
        "texture": 0.06,
    }
    role_pan = {
        "percussion": 0.0,
        "bass": -0.12,
        "piano": 0.32,
        "lead": -0.24,
        "texture": 0.42,
    }

    for event in events:
        start = int(event.start_seconds * SAMPLE_RATE)
        length = int(event.duration_seconds * SAMPLE_RATE)
        frequency = midi_to_frequency(event.pitch)
        gain = role_gain[event.role] * (event.velocity / 127)
        for sample_offset in range(length):
            index = start + sample_offset
            if index >= total_samples:
                break
            t = sample_offset / SAMPLE_RATE
            progress = sample_offset / float(length if length > 0 else 1)
            attack = min(1.0, t / 0.015)
            release_candidate = 1.0 - math.pow(progress, 1.7)
            release = release_candidate if release_candidate > 0.0 else 0.0
            envelope = attack * release
            signal = role_waveform(event.role, event.pitch, frequency, t, active_preset_id(live_control)) * gain * envelope
            pan = role_pan[event.role]
            left_gain = math.sqrt((1 - pan) / 2)
            right_gain = math.sqrt((1 + pan) / 2)
            left_samples[index] += signal * left_gain
            right_samples[index] += signal * right_gain

    peak = max(max(left_samples), abs(min(left_samples)), max(right_samples), abs(min(right_samples)), 0.01)
    scale = 0.88 / peak
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for left_value, right_value in zip(left_samples, right_samples, strict=True):
            frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, left_value * scale)) * 32767)))
            frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, right_value * scale)) * 32767)))
        wav_file.writeframes(bytes(frames))


def render_with_fluidsynth(midi_path: Path, wav_path: Path, soundfont_path: str | None) -> bool:
    fluidsynth = shutil.which("fluidsynth")
    if not fluidsynth or not soundfont_path:
        return False
    soundfont = Path(soundfont_path)
    if not soundfont.exists():
        return False
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(
        [fluidsynth, "-ni", str(soundfont), str(midi_path), "-F", str(wav_path), "-r", str(SAMPLE_RATE)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


def apply_effect_chain(wav_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    processed_path = wav_path.with_name(wav_path.stem + ".processed.wav")
    filters = "highpass=f=35,lowpass=f=13000,bass=g=2.5:f=90:w=0.6,treble=g=-1.5:f=6500,acompressor=threshold=-24dB:ratio=2.6:attack=18:release=220,aecho=0.45:0.28:80:0.16,volume=22dB,alimiter=limit=0.92"
    try:
        _ = subprocess.run(
            [ffmpeg, "-y", "-i", str(wav_path), "-af", filters, str(processed_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processed_path.replace(wav_path)
    except subprocess.CalledProcessError:
        if processed_path.exists():
            processed_path.unlink()


def render_audio(events: list[Event], midi_path: Path, wav_path: Path, soundfont_path: str | None = None, live_control: LiveControl | None = None) -> str:
    resolved_soundfont = soundfont_path or os.environ.get("SOUNDFONT_PATH")
    if render_with_fluidsynth(midi_path, wav_path, resolved_soundfont):
        apply_effect_chain(wav_path)
        return "fluidsynth+effects"
    synthesize_wav(events, wav_path, live_control)
    apply_effect_chain(wav_path)
    return "internal_synth+effects"


def variable_length_quantity(value: int) -> bytes:
    bytes_out = [value & 0x7F]
    value >>= 7
    while value > 0:
        bytes_out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(bytes_out)


def write_midi(events: list[Event], midi_path: Path, live_control: LiveControl | None = None) -> None:
    ordered: list[tuple[int, int, int, int, int]] = []
    channel_by_role = {"percussion": 9, "bass": 0, "piano": 1, "lead": 2, "texture": 3}
    program_by_role = midi_programs_for(live_control)
    instrument_by_role = selected_instruments_for(live_control)

    for event in events:
        start_tick = int(((event.bar - 1) * BEATS_PER_BAR + (event.beat - 1)) * TICKS_PER_BEAT)
        end_tick = start_tick + int(event.duration_beats * TICKS_PER_BEAT)
        channel = channel_by_role[event.role]
        ordered.append((start_tick, 1, channel, event.pitch, event.velocity))
        ordered.append((end_tick, 0, channel, event.pitch, 0))

    track = bytearray()
    # Tempo meta event makes the MIDI artifact and any FluidSynth render honor
    # prompt-derived tempo instead of falling back to a player default.
    microseconds_per_quarter = int(60_000_000 / TEMPO_BPM)
    track.extend(variable_length_quantity(0))
    track.extend(b"\xff\x51\x03" + microseconds_per_quarter.to_bytes(3, "big"))
    signature = effective_time_signature(live_control)
    denominator = int(METER_PRESETS[signature]["denominator"])
    denominator_power = int(math.log2(denominator))
    track.extend(variable_length_quantity(0))
    track.extend(bytes([0xFF, 0x58, 0x04, BEATS_PER_BAR, denominator_power, 24, 8]))

    for role, program in program_by_role.items():
        channel = channel_by_role[role]
        bank = instrument_by_role.get(role, {}).get("bank", 0)
        bank_msb = int(clamp(int(bank), 0, 127)) if isinstance(bank, int | float) else 0
        track.extend(variable_length_quantity(0))
        track.extend(bytes([0xB0 | channel, 0, bank_msb]))
        track.extend(variable_length_quantity(0))
        track.extend(bytes([0xC0 | channel, program]))

    last_tick = 0
    for tick, order, channel, pitch, velocity in sorted(ordered):
        delta = tick - last_tick
        last_tick = tick
        track.extend(variable_length_quantity(delta))
        if order == 1:
            track.extend(bytes([0x90 | channel, pitch, velocity]))
        else:
            track.extend(bytes([0x80 | channel, pitch, 0]))

    track.extend(variable_length_quantity(0))
    track.extend(b"\xff\x2f\x00")

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_BEAT)
    track_chunk = b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    _ = midi_path.write_bytes(header + track_chunk)


def read_variable_length_quantity(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset


def ticks_to_bar_beat(ticks: int) -> tuple[int, float]:
    total_beats = ticks / TICKS_PER_BEAT
    bar = int(total_beats // BEATS_PER_BAR) + 1
    beat = (total_beats % BEATS_PER_BAR) + 1
    return bar, beat


def parse_generated_midi(midi_path: Path) -> list[Event]:
    data = midi_path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("Generated MIDI header is missing")
    track_start = data.index(b"MTrk")
    track_length = int.from_bytes(data[track_start + 4 : track_start + 8], "big")
    track = data[track_start + 8 : track_start + 8 + track_length]
    role_by_channel = {9: "percussion", 0: "bass", 1: "piano", 2: "lead", 3: "texture"}
    active: dict[tuple[int, int], tuple[int, int]] = {}
    events: list[Event] = []
    offset = 0
    tick = 0

    while offset < len(track):
        delta, offset = read_variable_length_quantity(track, offset)
        tick += delta
        status = track[offset]
        offset += 1

        if status == 0xFF:
            meta_type = track[offset]
            offset += 1
            length, offset = read_variable_length_quantity(track, offset)
            offset += length
            if meta_type == 0x2F:
                break
            continue

        message_type = status & 0xF0
        channel = status & 0x0F
        if message_type == 0xC0:
            offset += 1
            continue

        if message_type == 0xB0:
            offset += 2
            continue

        if message_type in {0x80, 0x90}:
            pitch = track[offset]
            velocity = track[offset + 1]
            offset += 2
            key = (channel, pitch)
            if message_type == 0x90 and velocity > 0:
                active[key] = (tick, velocity)
            elif key in active:
                start_tick, start_velocity = active.pop(key)
                role = role_by_channel.get(channel)
                if role:
                    bar, beat = ticks_to_bar_beat(start_tick)
                    duration_beats = (tick - start_tick) / TICKS_PER_BEAT
                    events.append(Event(role, bar, beat, duration_beats, pitch, start_velocity))
            continue

        raise ValueError(f"Unsupported MIDI message: {status:#x}")

    return events


def write_manifest(events: list[Event], manifest_path: Path, seed: int, live_control: LiveControl, render_engine: str) -> None:
    tempo_bpm = effective_tempo_bpm(live_control)
    key = effective_key(live_control)
    roles = sorted({event.role for event in events})
    event_payload: list[EventJson] = [
        {
            "role": event.role,
            "bar": event.bar,
            "beat": event.beat,
            "duration_beats": event.duration_beats,
            "pitch": event.pitch,
            "velocity": event.velocity,
        }
        for event in events
    ]
    payload = {
        "tempo_bpm": tempo_bpm,
        "key": key,
        "bars": TOTAL_BARS,
        "roles": roles,
        "stream": "index.m3u8",
        "status": {role: "playing" for role in roles},
        "events": event_payload,
        "seed": seed,
        "live_control": live_control,
        "render_engine": render_engine,
        "active_preset": active_preset_id(live_control),
        "generation_params": live_control.get("generation_params"),
        "selected_instruments": selected_instruments_for(live_control),
        "soundfont": soundfont_metadata(),
        "time_signature": effective_time_signature(live_control),
    }
    _ = manifest_path.write_text(json.dumps(payload, indent=2) + "\n")


def create_recording(wav_path: Path, recording_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")
    recording_path.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(
        [ffmpeg, "-y", "-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "192k", str(recording_path)],
        check=True,
    )


def archive_run(output_dir: Path, recording_path: Path, archive_root: Path) -> ArchiveEntry:
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = created_at.replace(":", "").replace("-", "").replace("Z", "")
    run_dir = archive_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "recording": (recording_path, run_dir / "recording.mp3"),
        "midi": (output_dir / "ensemble.mid", run_dir / "ensemble.mid"),
        "wav": (output_dir / "ensemble.wav", run_dir / "ensemble.wav"),
        "state": (output_dir / "state.json", run_dir / "state.json"),
    }
    for source, destination in files.values():
        _ = shutil.copy2(source, destination)

    state = cast(WebsiteState, json.loads((output_dir / "state.json").read_text()))
    entry: ArchiveEntry = {
        "id": run_id,
        "created_at": created_at,
        "title": f"Dummy ensemble run {created_at}",
        "recording": f"/public/archive/{run_id}/recording.mp3",
        "midi": f"/public/archive/{run_id}/ensemble.mid",
        "wav": f"/public/archive/{run_id}/ensemble.wav",
        "state": f"/public/archive/{run_id}/state.json",
        "tempo_bpm": state["tempo_bpm"],
        "key": state["key"],
        "roles": state["roles"],
        "prompt": state["live_control"]["prompt"],
        "style_config": state["live_control"],
        "render_engine": state["render_engine"],
    }
    soundfont = state.get("soundfont")
    if soundfont is not None:
        entry["soundfont"] = soundfont
    time_signature = state.get("time_signature")
    if isinstance(time_signature, str):
        entry["time_signature"] = time_signature

    index_path = archive_root / "index.json"
    if index_path.exists():
        archive_index = cast(list[ArchiveEntry], json.loads(index_path.read_text()))
    else:
        archive_index = []
    archive_index.insert(0, entry)
    _ = index_path.write_text(json.dumps(archive_index, indent=2) + "\n")
    return entry


def create_hls(wav_path: Path, stream_dir: Path, live_duration_seconds: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")
    for old_file in stream_dir.glob("*.ts"):
        old_file.unlink()
    playlist = stream_dir / "index.m3u8"
    if playlist.exists():
        playlist.unlink()

    command = [ffmpeg, "-y", "-re", "-stream_loop", "-1"]
    if live_duration_seconds > 0:
        command.extend(["-t", str(live_duration_seconds)])
    command.extend(
        [
            "-i",
            str(wav_path),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "hls",
            "-hls_time",
            "4",
            "-hls_list_size",
            "30",
            "-hls_flags",
            "omit_endlist",
            "-hls_segment_filename",
            str(stream_dir / "segment_%03d.ts"),
            str(playlist),
        ]
    )
    _ = subprocess.run(command, check=True)


def build_session_id(session_id: str | None) -> str:
    if session_id:
        return session_id
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return "session-" + created_at.replace(":", "").replace("-", "").replace("Z", "")


def playable_session_chunks(session_dir: Path) -> list[Path]:
    chunk_paths = sorted(session_dir.glob("chunk_*.mp3"))
    playable: list[Path] = []
    for chunk_path in chunk_paths:
        if chunk_path.stat().st_size >= 4096:
            playable.append(chunk_path)
    if len(playable) > 1:
        return playable[:-1]
    return playable


def concatenate_session_recording(session_dir: Path, chunks: list[Path]) -> Path | None:
    if not chunks:
        return None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")
    concat_list = session_dir / "concat.txt"
    recording_path = session_dir / "current-stream.mp3"
    temp_recording_path = session_dir / "current-stream.tmp.mp3"
    concat_lines = [f"file '{chunk_path.resolve().as_posix()}'" for chunk_path in chunks]
    _ = concat_list.write_text("\n".join(concat_lines) + "\n")
    _ = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(temp_recording_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    temp_recording_path.replace(recording_path)
    return recording_path


def write_session_indexes(session_dir: Path, public_root: Path, session_id: str, created_at: str, chunk_seconds: int) -> None:
    chunks: list[SessionChunk] = []
    playable_chunks = playable_session_chunks(session_dir)
    session_recording = concatenate_session_recording(session_dir, playable_chunks)
    for chunk_path in reversed(playable_chunks):
        chunk_id = chunk_path.stem.replace("chunk_", "")
        chunks.append(
            {
                "id": chunk_id,
                "created_at": chunk_id,
                "recording": f"/public/sessions/{session_id}/{chunk_path.name}",
                "title": f"Current stream chunk {chunk_id}",
            }
        )

    payload: StreamSession = {
        "id": session_id,
        "created_at": created_at,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "title": f"Current stream session {session_id}",
        "chunk_seconds": chunk_seconds,
        "duration_seconds": float(len(playable_chunks) * chunk_seconds),
        "recording": f"/public/sessions/{session_id}/{session_recording.name}" if session_recording else None,
        "chunks": chunks,
    }
    session_dir.mkdir(parents=True, exist_ok=True)
    _ = (session_dir / "index.json").write_text(json.dumps(payload, indent=2) + "\n")
    _ = (public_root / "current-session.json").write_text(json.dumps(payload, indent=2) + "\n")


def start_session_recorder(
    wav_path: Path,
    public_root: Path,
    session_id: str,
    chunk_seconds: int,
    live_duration_seconds: int,
) -> tuple[subprocess.Popen[bytes], threading.Event, threading.Thread]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")

    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    session_dir = public_root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    write_session_indexes(session_dir, public_root, session_id, created_at, chunk_seconds)

    command = [ffmpeg, "-y", "-re", "-stream_loop", "-1"]
    if live_duration_seconds > 0:
        command.extend(["-t", str(live_duration_seconds)])
    command.extend(
        [
            "-i",
            str(wav_path),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            str(session_dir / "chunk_%Y%m%dT%H%M%S.mp3"),
        ]
    )
    process = subprocess.Popen(command)
    stop_event = threading.Event()

    def monitor_session() -> None:
        while not stop_event.is_set():
            write_session_indexes(session_dir, public_root, session_id, created_at, chunk_seconds)
            _ = stop_event.wait(2)
        write_session_indexes(session_dir, public_root, session_id, created_at, chunk_seconds)

    monitor_thread = threading.Thread(target=monitor_session, daemon=True)
    monitor_thread.start()
    return process, stop_event, monitor_thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Day 1 dummy ensemble stream.")
    _ = parser.add_argument("--output", default="public/stream", type=str, help="Output directory for generated stream files.")
    _ = parser.add_argument(
        "--live-duration-seconds",
        default=72,
        type=int,
        help="How long to generate rolling HLS for QA. Use 0 to run indefinitely.",
    )
    _ = parser.add_argument(
        "--session-id",
        default=None,
        type=str,
        help="Stable current-stream session id. Reuse the same value to append chunks to the same session.",
    )
    _ = parser.add_argument(
        "--session-chunk-seconds",
        default=300,
        type=int,
        help="Length of each saved current-stream MP3 chunk.",
    )
    _ = parser.add_argument(
        "--bars",
        default=128,
        type=int,
        help="How many bars to compose before the stream loops. Larger values reduce obvious repetition.",
    )
    _ = parser.add_argument(
        "--seed",
        default=None,
        type=int,
        help="Optional seed for reproducible musical variation. Omit it to generate a fresh riff each run.",
    )
    _ = parser.add_argument(
        "--soundfont",
        default=os.environ.get("SOUNDFONT_PATH"),
        type=str,
        help="Optional .sf2/.sf3 soundfont path. Requires fluidsynth; otherwise the internal synth is used.",
    )
    args: Namespace = parser.parse_args()

    global TOTAL_BARS
    output_dir = Path(cast(str, args.output))
    live_duration_seconds = cast(int, args.live_duration_seconds)
    session_chunk_seconds = cast(int, args.session_chunk_seconds)
    session_id = build_session_id(cast(str | None, args.session_id))
    TOTAL_BARS = cast(int, args.bars)
    seed = cast(int | None, args.seed)
    if seed is None:
        seed = random.SystemRandom().randint(1, 2_147_483_647)
    output_dir.mkdir(parents=True, exist_ok=True)
    public_root = output_dir.parent
    live_control = read_live_control(public_root)
    apply_live_control_meter(live_control)
    personas = read_personas(public_root)
    events = build_events(seed, live_control)
    soundfont_path = cast(str | None, args.soundfont)
    wav_path = output_dir / "ensemble.wav"
    midi_path = output_dir / "ensemble.mid"
    manifest_path = output_dir / "state.json"
    recording_path = public_root / "recordings" / "dummy-live-recording.mp3"
    archive_root = public_root / "archive"

    write_midi(events, midi_path, live_control)
    midi_events = parse_generated_midi(midi_path)
    render_engine = render_audio(midi_events, midi_path, wav_path, soundfont_path, live_control)
    write_manifest(midi_events, manifest_path, seed, live_control, render_engine)
    create_recording(wav_path, recording_path)
    archive_entry = archive_run(output_dir, recording_path, archive_root)
    session_process, stop_session_monitor, session_monitor = start_session_recorder(
        wav_path,
        public_root,
        session_id,
        session_chunk_seconds,
        live_duration_seconds,
    )
    try:
        create_hls(wav_path, output_dir, live_duration_seconds)
    finally:
        stop_session_monitor.set()
        session_monitor.join(timeout=3)
        if session_process.poll() is None:
            session_process.terminate()
            try:
                session_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                session_process.kill()
                session_process.wait(timeout=5)

    print(f"Generated {midi_path}")
    print(f"Generated {wav_path} from parsed MIDI events")
    print(f"Generated {manifest_path}")
    print(f"Generated {recording_path}")
    print(f"Archived run {archive_entry['id']}")
    print(f"Current stream session {session_id}")
    print(f"Variation seed {seed}")
    print(f"Live prompt {live_control['prompt']}")
    print(f"Render engine {render_engine}")
    print(f"Loaded {len(personas)} personas")
    print(f"Generated {output_dir / 'index.m3u8'}")


if __name__ == "__main__":
    main()
