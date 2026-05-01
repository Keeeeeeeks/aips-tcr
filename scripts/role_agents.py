#!/usr/bin/env python3
"""Role-agent bundle generation and validation for the segment conductor."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Literal, TypedDict, cast

import generate_dummy_stream as dummy


RoleName = Literal["percussion", "bass", "piano", "lead", "texture"]
ROLE_NAMES: tuple[RoleName, ...] = ("percussion", "bass", "piano", "lead", "texture")


class RoleEvent(TypedDict):
    bar: int
    beat: float
    duration_beats: float
    pitch: int
    velocity: int


class RoleBundleMetadata(TypedDict):
    density: float
    solo_intensity: float
    supports_soloist: bool
    source: str
    instrument: dict[str, object]


class RoleBundle(TypedDict):
    segment_id: int
    role: RoleName
    status: str
    events: list[RoleEvent]
    metadata: RoleBundleMetadata


class ConductorState(TypedDict):
    segment_id: int
    tempo_bpm: int
    key: str
    section_bars: int
    active_soloist: str
    psychosis_level: float
    live_prompt: str
    role_directives: dict[str, str]
    generation_params: dummy.GenerationParams | None
    time_signature: str
    beats_per_bar: int


class LlmRuntimeStatus(TypedDict):
    connected: bool
    mode: str
    source: str
    message: str


def build_conductor_state(
    segment_id: int,
    section_bars: int,
    live_control: dummy.LiveControl,
    personas: dict[str, object],
    preset_modes: dict[str, object] | None = None,
) -> ConductorState:
    role_directives: dict[str, str] = {}
    preset_modes = preset_modes or {}
    active_profile = preset_modes.get("active_profile")
    active_roles_raw = preset_modes.get("active_roles")
    profiles_raw = preset_modes.get("profiles")
    active_roles = active_roles_raw if isinstance(active_roles_raw, dict) else {}
    profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
    active_preset = profiles.get(active_profile) if isinstance(active_profile, str) else None
    active_preset_label = ""
    active_preset_roles: dict[str, object] = {}
    if isinstance(active_preset, dict):
        label = active_preset.get("label")
        roles = active_preset.get("roles")
        active_preset_label = label if isinstance(label, str) else str(active_profile)
        active_preset_roles = roles if isinstance(roles, dict) else {}
    for role in ROLE_NAMES:
        persona = personas.get(role)
        if isinstance(persona, dict) and isinstance(persona.get("prompt"), str):
            directive = cast(str, persona["prompt"])
        else:
            directive = f"Play a sparse supportive {role} part."
        if bool(active_roles.get(role, True)):
            overlay = active_preset_roles.get(role)
            if isinstance(overlay, str) and overlay.strip():
                directive = directive + f"\n\nPreset mode overlay ({active_preset_label}): " + overlay.strip()
        role_directives[role] = directive

    prompt = live_control["prompt"].lower()
    active_soloist = "lead"
    if "drum" in prompt or "break" in prompt:
        active_soloist = "percussion"
    elif "bass" in prompt:
        active_soloist = "bass"
    elif "texture" in prompt or "haunted" in prompt:
        active_soloist = "texture"

    return {
        "segment_id": segment_id,
        "tempo_bpm": dummy.effective_tempo_bpm(live_control),
        "key": dummy.effective_key(live_control),
        "section_bars": section_bars,
        "active_soloist": active_soloist,
        "psychosis_level": live_control["psychosis_level"],
        "live_prompt": live_control["prompt"],
        "role_directives": role_directives,
        "generation_params": live_control.get("generation_params"),
        "time_signature": dummy.effective_time_signature(live_control),
        "beats_per_bar": int(dummy.METER_PRESETS[dummy.effective_time_signature(live_control)]["beats_per_bar"]),
    }


def generation_params_prompt(conductor_state: ConductorState, live_control: dummy.LiveControl) -> str:
    active_preset = dummy.active_preset_id(live_control)
    preset_arrangement = dummy.arrangement_for(live_control)
    preset_programs = dummy.midi_programs_for(live_control)
    return json.dumps(
        {
            "instruction": "You are the conductor planner for a symbolic AI ensemble. Encode the listener's live_prompt into one compact JSON generation_params object. Do not emit note events. Return strict JSON only.",
            "live_prompt": conductor_state["live_prompt"],
            "tempo_bpm": conductor_state["tempo_bpm"],
            "key": conductor_state["key"],
            "psychosis_level": conductor_state["psychosis_level"],
            "active_preset": active_preset,
            "preset_arrangement_reference": preset_arrangement,
            "preset_midi_program_reference": preset_programs,
            "schema": {
                "source": "llm_generation_params",
                "summary": "short audible intent",
                "chords": [[0, 3, 7], [5, 8, 12], [-2, 3, 7], [0, 5, 10]],
                "bass": [-24, -17, -19, -12],
                "lead_shapes": [[0, 2, 3, 7], [7, 5, 3, 0]],
                "texture": [19, 24, 31, 36],
                "density": 1.0,
                "midi_programs": {"bass": 33, "piano": 4, "lead": 65, "texture": 89},
            },
            "constraints": [
                "All pitch values are semitone offsets from the detected key root, not absolute MIDI notes.",
                "Return 2 to 8 chord rows; each chord row has 2 to 5 integer intervals from -24 to 36.",
                "Return 2 to 8 bass offsets from -36 to 12.",
                "Return 2 to 8 lead_shapes; each shape has 2 to 8 integer intervals from -12 to 36.",
                "Return 2 to 8 texture offsets from 0 to 48.",
                "density must be between 0.2 and 2.4.",
                "MIDI programs must be integers from 0 to 127 for bass, piano, lead, and texture only.",
                "Stay close enough to the active preset to preserve continuity, but make concrete changes requested by the live_prompt.",
            ],
        }
    )


def _clamp_int(value: object, minimum: int, maximum: int) -> int | None:
    if not isinstance(value, int):
        return None
    return int(dummy.clamp(value, minimum, maximum))


def _parse_int_list(value: object, minimum: int, maximum: int, min_len: int, max_len: int) -> list[int] | None:
    if not isinstance(value, list):
        return None
    parsed: list[int] = []
    for item in value[:max_len]:
        parsed_item = _clamp_int(item, minimum, maximum)
        if parsed_item is not None:
            parsed.append(parsed_item)
    if len(parsed) < min_len:
        return None
    return parsed


def _parse_int_matrix(value: object, minimum: int, maximum: int, min_rows: int, max_rows: int, min_cols: int, max_cols: int) -> list[list[int]] | None:
    if not isinstance(value, list):
        return None
    parsed: list[list[int]] = []
    for row in value[:max_rows]:
        parsed_row = _parse_int_list(row, minimum, maximum, min_cols, max_cols)
        if parsed_row is not None:
            parsed.append(parsed_row)
    if len(parsed) < min_rows:
        return None
    return parsed


def parse_generation_params(raw_params: object, live_control: dummy.LiveControl) -> dummy.GenerationParams:
    if not isinstance(raw_params, dict):
        raise ValueError("generation_params must be an object")
    params = cast(dict[str, object], raw_params)
    fallback_arrangement = dummy.arrangement_for(live_control)
    fallback_programs = dummy.midi_programs_for(live_control)
    fallback_density = fallback_arrangement.get("density", 1.0)
    summary = params.get("summary")
    chords = _parse_int_matrix(params.get("chords"), -24, 36, 2, 8, 2, 5)
    bass = _parse_int_list(params.get("bass"), -36, 12, 2, 8)
    lead_shapes = _parse_int_matrix(params.get("lead_shapes"), -12, 36, 2, 8, 2, 8)
    texture = _parse_int_list(params.get("texture"), 0, 48, 2, 8)
    raw_density = params.get("density")
    density = float(raw_density) if isinstance(raw_density, int | float) else float(fallback_density) if isinstance(fallback_density, int | float) else 1.0
    raw_programs = params.get("midi_programs")
    midi_programs = dict(fallback_programs)
    if isinstance(raw_programs, dict):
        for role in ["bass", "piano", "lead", "texture"]:
            program = _clamp_int(raw_programs.get(role), 0, 127)
            if program is not None:
                midi_programs[role] = program
    return {
        "source": "llm_generation_params",
        "summary": summary.strip()[:160] if isinstance(summary, str) and summary.strip() else "Live prompt encoded into structured generation parameters.",
        "chords": chords if chords is not None else cast(list[list[int]], fallback_arrangement["chords"]),
        "bass": bass if bass is not None else cast(list[int], fallback_arrangement["bass"]),
        "lead_shapes": lead_shapes if lead_shapes is not None else cast(list[list[int]], fallback_arrangement["lead_shapes"]),
        "texture": texture if texture is not None else cast(list[int], fallback_arrangement["texture"]),
        "density": dummy.clamp(density, 0.2, 2.4),
        "midi_programs": midi_programs,
    }


def plan_generation_params_with_status(
    conductor_state: ConductorState,
    live_control: dummy.LiveControl,
    agent_mode: str,
) -> tuple[dummy.GenerationParams | None, LlmRuntimeStatus]:
    if agent_mode != "llm":
        return None, {
            "connected": False,
            "mode": agent_mode,
            "source": "heuristic",
            "message": "Generation parameter planning is only active in LLM mode.",
        }
    try:
        raw_text = call_openai_compatible(generation_params_prompt(conductor_state, live_control))
        raw_params = json.loads(raw_text)
        return parse_generation_params(raw_params, live_control), {
            "connected": True,
            "mode": "llm",
            "source": "llm_generation_params",
            "message": "LLM encoded the live prompt into structured generation parameters.",
        }
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        return None, {
            "connected": False,
            "mode": "llm",
            "source": "generation_params_fallback",
            "message": f"LLM generation-parameter planning failed; preset/heuristic parameters remain active: {error}",
        }


def event_to_role_event(event: dummy.Event) -> RoleEvent:
    return {
        "bar": event.bar,
        "beat": event.beat,
        "duration_beats": event.duration_beats,
        "pitch": event.pitch,
        "velocity": event.velocity,
    }


def heuristic_role_bundles(conductor_state: ConductorState, seed: int, live_control: dummy.LiveControl) -> list[RoleBundle]:
    dummy.TOTAL_BARS = conductor_state["section_bars"]
    events = dummy.build_events(seed, live_control)
    bundles: list[RoleBundle] = []
    for role in ROLE_NAMES:
        role_events = [event_to_role_event(event) for event in events if event.role == role]
        density = min(1.0, len(role_events) / max(1, conductor_state["section_bars"] * 8))
        bundles.append(
            {
                "segment_id": conductor_state["segment_id"],
                "role": role,
                "status": "playing" if role_events else "resting",
                "events": role_events,
            "metadata": {
                "density": density,
                "solo_intensity": 0.55 if conductor_state["active_soloist"] == role else 0.12,
                "supports_soloist": conductor_state["active_soloist"] != role,
                "source": "heuristic",
                "instrument": dummy.selected_instruments_for(live_control).get(role, {}),
            },
            }
        )
    return bundles


def mark_bundle_source(bundles: list[RoleBundle], source: str) -> list[RoleBundle]:
    for bundle in bundles:
        bundle["metadata"]["source"] = source
    return bundles


def role_agent_prompt(conductor_state: ConductorState, role: RoleName) -> str:
    return json.dumps(
        {
            "instruction": "You are a symbolic music role agent. Return only one JSON role bundle. Do not include markdown. The listener's live_prompt is mandatory: make concrete musical choices that audibly reflect it in rhythm, density, register, pitch shape, and velocity. Do not keep looping a generic style when the live_prompt asks for a change.",
            "role": role,
            "conductor_state": conductor_state,
            "role_directive": conductor_state["role_directives"].get(role, "Play sparsely and support the ensemble."),
            "live_prompt_to_follow": conductor_state["live_prompt"],
            "schema": {
                "segment_id": conductor_state["segment_id"],
                "role": role,
                "status": "playing",
                "events": [
                    {"bar": 1, "beat": 1.0, "duration_beats": 1.0, "pitch": 57, "velocity": 70}
                ],
            "metadata": {"density": 0.4, "solo_intensity": 0.1, "supports_soloist": True, "instrument": dummy.selected_instruments_for().get(role, {})},
            },
            "constraints": [
                "Use MIDI pitch numbers between 21 and 108.",
                "Use bars within this segment only.",
                f"Use beat values from 1.0 through {conductor_state['beats_per_bar']}.99 for this {conductor_state['time_signature']} section.",
                "Keep durations positive and at most 8 beats.",
                "Tempo and key are conductor-level controls already applied in conductor_state; do not override them inside a role bundle.",
                "If uncertain, emit a sparse safe support pattern.",
                "If live_prompt asks for a genre, energy, mood, or instrumentation change, make this role's events obviously reflect that request in this section.",
                "Vary each segment from the previous generic loop; avoid repeating the same rhythm/register shape by default.",
            ],
        }
    )


def call_openai_compatible(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    timeout_seconds = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "8"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_response = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"LLM request failed: {error}") from error
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM response did not include choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("LLM choice was not an object")
    message = first_choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise RuntimeError("LLM message content was missing")
    return cast(str, message["content"])


def parse_role_bundle(raw_bundle: object, role: RoleName, segment_id: int) -> RoleBundle:
    if not isinstance(raw_bundle, dict):
        raise ValueError("Role bundle must be an object")
    raw_events = raw_bundle.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("Role bundle events must be a list")

    events: list[RoleEvent] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        bar = raw_event.get("bar")
        beat = raw_event.get("beat")
        duration_beats = raw_event.get("duration_beats")
        pitch = raw_event.get("pitch")
        velocity = raw_event.get("velocity")
        if not isinstance(bar, int):
            continue
        if not isinstance(beat, int | float) or not isinstance(duration_beats, int | float):
            continue
        if not isinstance(pitch, int) or not isinstance(velocity, int):
            continue
        events.append(
            {
                "bar": bar,
                "beat": float(beat),
                "duration_beats": float(duration_beats),
                "pitch": pitch,
                "velocity": velocity,
            }
        )

    metadata: RoleBundleMetadata = {
        "density": min(1.0, len(events) / 16),
        "solo_intensity": 0.1,
        "supports_soloist": True,
        "source": "llm",
        "instrument": dummy.selected_instruments_for().get(role, {}),
    }
    return {
        "segment_id": segment_id,
        "role": role,
        "status": "playing" if events else "resting",
        "events": events,
        "metadata": metadata,
    }


def llm_role_bundles(conductor_state: ConductorState) -> list[RoleBundle]:
    bundles: list[RoleBundle] = []
    for role in ROLE_NAMES:
        prompt = role_agent_prompt(conductor_state, role)
        raw_text = call_openai_compatible(prompt)
        raw_bundle = json.loads(raw_text)
        bundles.append(parse_role_bundle(raw_bundle, role, conductor_state["segment_id"]))
    return bundles


def fallback_bundle(role: RoleName, segment_id: int, section_bars: int) -> RoleBundle:
    pitch_by_role: dict[RoleName, int] = {"percussion": 42, "bass": 45, "piano": 64, "lead": 69, "texture": 81}
    events: list[RoleEvent] = []
    for bar in range(1, section_bars + 1):
        duration = 0.2 if role == "percussion" else 2.0
        velocity = 50 if role != "texture" else 30
        events.append({"bar": bar, "beat": 1.0, "duration_beats": duration, "pitch": pitch_by_role[role], "velocity": velocity})
    return {
        "segment_id": segment_id,
        "role": role,
        "status": "fallback",
        "events": events,
        "metadata": {"density": 0.15, "solo_intensity": 0.0, "supports_soloist": True, "source": "fallback", "instrument": dummy.selected_instruments_for().get(role, {})},
    }


def generate_role_bundles(
    conductor_state: ConductorState,
    seed: int,
    live_control: dummy.LiveControl,
    agent_mode: str,
) -> list[RoleBundle]:
    bundles, _status = generate_role_bundles_with_status(conductor_state, seed, live_control, agent_mode)
    return bundles


def generate_role_bundles_with_status(
    conductor_state: ConductorState,
    seed: int,
    live_control: dummy.LiveControl,
    agent_mode: str,
) -> tuple[list[RoleBundle], LlmRuntimeStatus]:
    if agent_mode == "llm":
        try:
            return llm_role_bundles(conductor_state), {
                "connected": True,
                "mode": "llm",
                "source": "llm",
                "message": "LLM role agents returned valid bundles for the latest section.",
            }
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            return mark_bundle_source(heuristic_role_bundles(conductor_state, seed, live_control), "heuristic_fallback"), {
                "connected": False,
                "mode": "llm",
                "source": "heuristic_fallback",
                "message": f"LLM mode requested, but the latest section fell back to heuristics: {error}",
            }
    return heuristic_role_bundles(conductor_state, seed, live_control), {
        "connected": False,
        "mode": agent_mode,
        "source": "heuristic",
        "message": "The segment conductor is running in heuristic mode, not LLM mode.",
    }


def flatten_and_validate_bundles(bundles: list[RoleBundle], section_bars: int) -> list[dummy.Event]:
    bundles_by_role = {bundle["role"]: bundle for bundle in bundles}
    flattened: list[dummy.Event] = []
    max_beat = float(dummy.BEATS_PER_BAR) + 0.99
    for role in ROLE_NAMES:
        bundle = bundles_by_role.get(role)
        if bundle is None:
            bundle = fallback_bundle(role, 0, section_bars)
        for event in bundle["events"]:
            bar = max(1, min(section_bars, event["bar"]))
            beat = max(1.0, min(max_beat, event["beat"]))
            duration = max(0.05, min(8.0, event["duration_beats"]))
            pitch = max(21, min(108, event["pitch"]))
            velocity = max(1, min(127, event["velocity"]))
            flattened.append(dummy.Event(role, bar, beat, duration, pitch, velocity))
    return sorted(flattened, key=lambda item: (item.bar, item.beat, item.role, item.pitch))
