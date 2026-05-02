#!/usr/bin/env python3
"""Local writable control server for the AI ensemble demo."""

from __future__ import annotations

import json
import argparse
import http.cookies
import ipaddress
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import radio_state


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
PERSONAS_PATH = PUBLIC / "personas.json"
LIVE_CONTROL_PATH = PUBLIC / "live-control.json"
CONDUCTOR_STATUS_PATH = PUBLIC / "conductor-status.json"
ROLE_BUNDLES_PATH = PUBLIC / "stream" / "role-bundles.json"
PRESET_MODES_PATH = PUBLIC / "preset-modes.json"
ROLE_KEYS = {"percussion", "bass", "piano", "lead", "texture"}
SERVER_STARTED_AT = time.time()
RADIO_TZ = ZoneInfo("America/New_York")
RADIO_LIVE_START_HOUR = int(os.environ.get("AIPS_RADIO_LIVE_START_HOUR", "5"))
RADIO_LIVE_END_HOUR = int(os.environ.get("AIPS_RADIO_LIVE_END_HOUR", "19"))
_NET_CACHE: dict[str, float] = {"ts": 0.0, "bytes": 0.0}
ADMIN_COOKIE = "aips_admin_session"
VOTER_COOKIE = "aips_voter_id"
ADMIN_OVERRIDE_PATH = radio_state.paths(ROOT)["state_dir"] / "admin-override.json"
FALLBACK_MODE_PATH = radio_state.paths(ROOT)["state_dir"] / "fallback-mode.json"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    _ = temp_path.write_text(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > 64_000:
        raise ValueError("Request body must be between 1 byte and 64 KB")
    raw_body = handler.rfile.read(length)
    payload = json.loads(raw_body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return cast(dict[str, Any], payload)


def validate_personas(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    if set(payload.keys()) != ROLE_KEYS:
        raise ValueError("Personas must include exactly percussion, bass, piano, lead, and texture")

    personas: dict[str, dict[str, str]] = {}
    for role, raw_persona in payload.items():
        if not isinstance(raw_persona, dict):
            raise ValueError(f"Persona for {role} must be an object")
        label = raw_persona.get("label")
        purpose = raw_persona.get("purpose")
        prompt = raw_persona.get("prompt")
        if not isinstance(label, str) or not isinstance(purpose, str) or not isinstance(prompt, str):
            raise ValueError(f"Persona for {role} must include string label, purpose, and prompt")
        if not label.strip() or not purpose.strip() or not prompt.strip():
            raise ValueError(f"Persona for {role} cannot contain empty fields")
        personas[role] = {"label": label.strip(), "purpose": purpose.strip(), "prompt": prompt.strip()}
    return personas


def default_active_roles() -> dict[str, bool]:
    return {role: True for role in sorted(ROLE_KEYS)}


def validate_preset_modes(payload: dict[str, Any]) -> dict[str, object]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("preset modes must include a non-empty profiles object")

    clean_profiles: dict[str, object] = {}
    for profile_id, raw_profile in profiles.items():
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("profile ids must be non-empty strings")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"profile {profile_id} must be an object")
        label = raw_profile.get("label")
        description = raw_profile.get("description", "")
        live_prompt = raw_profile.get("live_prompt", "")
        psychosis_level = raw_profile.get("psychosis_level", 0.25)
        tempo_bpm = raw_profile.get("tempo_bpm", extract_prompt_tempo_bpm(str(live_prompt)))
        key = raw_profile.get("key", extract_prompt_key(str(live_prompt)))
        roles = raw_profile.get("roles", {})
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"profile {profile_id} must include a label")
        if not isinstance(description, str) or not isinstance(live_prompt, str):
            raise ValueError(f"profile {profile_id} description/live_prompt must be strings")
        if not isinstance(psychosis_level, int | float):
            raise ValueError(f"profile {profile_id} psychosis_level must be numeric")
        if not isinstance(tempo_bpm, int | float):
            raise ValueError(f"profile {profile_id} tempo_bpm must be numeric")
        if not isinstance(key, str):
            raise ValueError(f"profile {profile_id} key must be a string")
        if not isinstance(roles, dict):
            raise ValueError(f"profile {profile_id} roles must be an object")
        clean_roles: dict[str, str] = {}
        for role, prompt in roles.items():
            if role not in ROLE_KEYS:
                continue
            if isinstance(prompt, str) and prompt.strip():
                clean_roles[role] = prompt.strip()
        clean_profiles[profile_id.strip()] = {
            "label": label.strip(),
            "description": description.strip(),
            "live_prompt": " ".join(live_prompt.strip().split()),
            "psychosis_level": max(0.0, min(1.0, float(psychosis_level))),
            "tempo_bpm": max(60, min(220, int(tempo_bpm))),
            "key": key.strip() or "A minor",
            "roles": clean_roles,
        }

    active_profile = payload.get("active_profile", "none")
    if not isinstance(active_profile, str) or active_profile not in clean_profiles:
        active_profile = "none" if "none" in clean_profiles else next(iter(clean_profiles.keys()))

    raw_active_roles = payload.get("active_roles", default_active_roles())
    if not isinstance(raw_active_roles, dict):
        raw_active_roles = default_active_roles()
    active_roles = {role: bool(raw_active_roles.get(role, True)) for role in sorted(ROLE_KEYS)}

    return {
        "active_profile": active_profile,
        "active_roles": active_roles,
        "profiles": clean_profiles,
        "updated_at": utc_now(),
    }


def read_preset_modes() -> dict[str, Any] | None:
    return read_json_object(PRESET_MODES_PATH)


def extract_prompt_tempo_bpm(prompt: str, fallback: int = 92) -> int:
    match = re.search(r"\b(\d{2,3})\s*bpm\b", prompt.lower())
    if not match:
        return fallback
    return max(60, min(220, int(match.group(1))))


def extract_prompt_key(prompt: str, fallback: str = "A minor") -> str:
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


def validate_live_control(payload: dict[str, Any], allow_admin_meters: bool = False) -> dict[str, object]:
    prompt = payload.get("prompt", "")
    psychosis_level = payload.get("psychosis_level", 0.25)
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    if not isinstance(psychosis_level, int | float):
        raise ValueError("psychosis_level must be a number")

    clean_prompt = " ".join(prompt.strip().split())
    if len(clean_prompt) > 800:
        raise ValueError("prompt must be 800 characters or fewer")

    explicit_tempo = payload.get("tempo_bpm")
    explicit_key = payload.get("key")
    tempo_bpm = max(60, min(220, int(explicit_tempo))) if isinstance(explicit_tempo, int | float) else extract_prompt_tempo_bpm(clean_prompt)
    key = explicit_key.strip() if isinstance(explicit_key, str) and explicit_key.strip() else extract_prompt_key(clean_prompt)
    explicit_time_signature = payload.get("time_signature")
    allowed_meters = {"4/4", "3/4", "6/8", "5/4", "7/8"} if allow_admin_meters else {"4/4", "3/4", "6/8"}
    time_signature = explicit_time_signature if isinstance(explicit_time_signature, str) and explicit_time_signature in allowed_meters else "4/4"
    level = max(0.0, min(1.0, float(psychosis_level)))
    return {
        "prompt": clean_prompt,
        "psychosis_level": level,
        "updated_at": utc_now(),
        "applies_to": "next generated section",
        "delivery_status": "control_server_received; llm_segment_conductor_not_running_yet",
        "next_section_eta_seconds": None,
        "next_effect": "next generator run/form",
        "tempo_bpm": tempo_bpm,
        "key": key,
        "time_signature": time_signature,
    }


def validate_role_options(raw_role_options: object) -> dict[str, list[dict[str, str]]]:
    clean: dict[str, list[dict[str, str]]] = {role: [] for role in sorted(ROLE_KEYS)}
    if not isinstance(raw_role_options, dict):
        return clean
    for role, raw_options in raw_role_options.items():
        if role not in ROLE_KEYS or not isinstance(raw_options, list):
            continue
        role_clean: list[dict[str, str]] = []
        for item in raw_options[:8]:
            if isinstance(item, dict):
                option_id = str(item.get("id") or item.get("label") or "").strip().lower()
                option_id = re.sub(r"[^a-z0-9_-]+", "-", option_id).strip("-")
                label = str(item.get("label") or option_id).strip()[:80]
            elif isinstance(item, str):
                option_id = re.sub(r"[^a-z0-9_-]+", "-", item.strip().lower()).strip("-")
                label = item.strip()[:80]
            else:
                continue
            if option_id and label:
                role_clean.append({"id": option_id, "label": label})
        clean[role] = role_clean
    return clean


def read_fallback_mode() -> dict[str, object]:
    payload = read_json_object(FALLBACK_MODE_PATH) or {}
    enabled = payload.get("enabled") is True
    return {"enabled": enabled, "updated_at": payload.get("updated_at")}


def write_fallback_mode(enabled: bool) -> dict[str, object]:
    payload: dict[str, object] = {"enabled": enabled, "updated_at": utc_now()}
    write_json(FALLBACK_MODE_PATH, payload)
    return payload


def read_admin_override() -> dict[str, object]:
    return read_json_object(ADMIN_OVERRIDE_PATH) or {"enabled": False}


def write_admin_override(payload: dict[str, Any]) -> dict[str, object]:
    enabled = payload.get("enabled") is True
    override: dict[str, object] = {"enabled": enabled, "updated_at": utc_now()}
    if enabled:
        live_control = validate_live_control(payload, allow_admin_meters=True)
        override.update(live_control)
    write_json(ADMIN_OVERRIDE_PATH, override)
    return override


def attach_conductor_status(live_control: dict[str, object]) -> dict[str, object]:
    if not CONDUCTOR_STATUS_PATH.exists():
        return live_control
    try:
        status = json.loads(CONDUCTOR_STATUS_PATH.read_text())
    except json.JSONDecodeError:
        return live_control
    if not isinstance(status, dict):
        return live_control
    if status.get("delivery_status") == "segment_conductor_running" and status.get("status") in {"prebuffering", "generating", "waiting"}:
        live_control["delivery_status"] = "control_server_received; segment_conductor_will_apply_at_next_boundary"
        live_control["next_section_eta_seconds"] = status.get("next_section_eta_seconds")
        sections_until_prompt = status.get("prompt_sections_until_heard")
        if isinstance(sections_until_prompt, int):
            live_control["next_effect"] = f"audible in about {sections_until_prompt} buffered section(s)"
        else:
            live_control["next_effect"] = "next generated section; audible after the current buffer"
        live_control["conductor_status"] = status.get("status")
        live_control["conductor_section_index"] = status.get("section_index")
        live_control["live_ready"] = status.get("live_ready")
        live_control["buffered_sections"] = status.get("buffered_sections")
        live_control["sections_until_live"] = status.get("sections_until_live")
        live_control["prompt_sections_until_heard"] = sections_until_prompt
    return live_control


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


def check_llm_status() -> dict[str, object]:
    conductor = read_json_object(CONDUCTOR_STATUS_PATH)
    role_bundles = read_json_object(ROLE_BUNDLES_PATH)
    server_has_key = bool(os.environ.get("OPENAI_API_KEY"))

    base: dict[str, object] = {
        "ok": True,
        "server_has_openai_api_key": server_has_key,
        "connected": False,
        "mode_active": False,
        "latest_generation_connected": False,
        "conductor_running": False,
        "agent_mode": None,
        "source": None,
        "color": "red",
    }

    if conductor is None:
        return {
            **base,
            "message": "No conductor status file yet. Start scripts/segment_conductor.py with --agent-mode llm.",
        }

    conductor_running = conductor.get("delivery_status") == "segment_conductor_running" and conductor.get("status") in {"prebuffering", "generating", "waiting"}
    agent_mode = conductor.get("agent_mode")
    llm_status = conductor.get("llm_status")
    if not isinstance(llm_status, dict) and role_bundles is not None:
        llm_status = role_bundles.get("llm_status")

    latest_ok = isinstance(llm_status, dict) and llm_status.get("connected") is True
    source = llm_status.get("source") if isinstance(llm_status, dict) else None
    latest_message = str(llm_status.get("message", "")) if isinstance(llm_status, dict) else ""

    if agent_mode != "llm":
        return {
            **base,
            "conductor_running": conductor_running,
            "agent_mode": agent_mode,
            "message": "The conductor is running, but not in LLM mode. Restart it with --agent-mode llm.",
        }

    if not conductor_running:
        return {
            **base,
            "agent_mode": agent_mode,
            "mode_active": True,
            "message": "The conductor is configured for LLM mode but is not currently running.",
        }

    # `connected` now means: the conductor is actively running in LLM mode.
    # `latest_generation_connected` means: the latest section actually used LLM output.
    if latest_ok:
        message = latest_message or "LLM mode is active and the latest section used LLM role bundles."
        color = "green"
    else:
        message = latest_message or "LLM mode is active, but the latest section used heuristic fallback."
        color = "amber"

    return {
        **base,
        "connected": True,
        "mode_active": True,
        "latest_generation_connected": latest_ok,
        "conductor_running": True,
        "agent_mode": agent_mode,
        "source": source,
        "color": color,
        "message": message,
    }


def radio_window_status() -> dict[str, object]:
    now = datetime.now(RADIO_TZ)
    start = now.replace(hour=RADIO_LIVE_START_HOUR, minute=0, second=0, microsecond=0)
    end = now.replace(hour=RADIO_LIVE_END_HOUR, minute=0, second=0, microsecond=0)
    should_be_live = start <= now < end
    next_transition = end if should_be_live else start
    if next_transition <= now:
        next_transition = next_transition + timedelta(days=1)

    conductor = read_json_object(CONDUCTOR_STATUS_PATH) or {}
    conductor_running = conductor.get("delivery_status") == "segment_conductor_running" and conductor.get("status") in {"prebuffering", "generating", "waiting"}
    live_ready = conductor.get("live_ready") is True
    if should_be_live and conductor_running and live_ready:
        state = "live"
        message = "Radio is live and the stream buffer is ready."
    elif should_be_live and conductor_running:
        state = "opening"
        message = "Radio window is open; conductor is prebuffering audio."
    elif should_be_live:
        state = "opening"
        message = "Radio window is open; start the backend conductor to go live."
    else:
        state = "offline"
        message = "Radio is offline outside the 5:00 AM–7:00 PM EST broadcast window."

    return {
        "ok": True,
        "state": state,
        "should_be_live": should_be_live,
        "timezone": "America/New_York",
        "window_label": "5:00 AM–7:00 PM EST",
        "now_eastern": now.isoformat(),
        "next_transition_label": "closes at" if should_be_live else "opens at",
        "next_transition_at_eastern": next_transition.strftime("%-I:%M %p %Z"),
        "next_transition_seconds": max(0, int((next_transition - now).total_seconds())),
        "conductor_running": conductor_running,
        "live_ready": live_ready,
        "session_id": conductor.get("session_id"),
        "conductor_status": conductor.get("status"),
        "message": message,
    }

def _read_cpu_pct() -> float:
    try:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return max(0.0, min(100.0, (load / cores) * 100.0))
    except (OSError, AttributeError):
        return 0.0


def _read_ram_pct_macos() -> float | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(["vm_stat"], text=True, timeout=2.0)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    page_size = 4096
    stats: dict[str, int] = {}
    for line in out.splitlines():
        match_size = re.match(r"^Mach Virtual Memory Statistics.*page size of (\d+)", line)
        if match_size:
            page_size = int(match_size.group(1))
            continue
        match_kv = re.match(r"^([^:]+):\s+(\d+)\.?", line)
        if match_kv:
            stats[match_kv.group(1).strip()] = int(match_kv.group(2))
    free = stats.get("Pages free", 0)
    active = stats.get("Pages active", 0)
    inactive = stats.get("Pages inactive", 0)
    speculative = stats.get("Pages speculative", 0)
    wired = stats.get("Pages wired down", 0)
    compressed = stats.get("Pages occupied by compressor", 0)
    used = (active + wired + compressed) * page_size
    total = (free + active + inactive + speculative + wired + compressed) * page_size
    if total <= 0:
        return None
    return max(0.0, min(100.0, (used / total) * 100.0))


def _read_ram_pct_linux() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            meminfo: dict[str, int] = {}
            for line in handle:
                parts = line.split(":")
                if len(parts) != 2:
                    continue
                tokens = parts[1].strip().split()
                if tokens:
                    meminfo[parts[0]] = int(tokens[0])
    except OSError:
        return None
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if not total or available is None:
        return None
    used = total - available
    return max(0.0, min(100.0, (used / total) * 100.0))


def _read_ram_pct() -> float:
    return _read_ram_pct_macos() or _read_ram_pct_linux() or 0.0


def _read_net_total_bytes_macos() -> float | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(["netstat", "-ibn"], text=True, timeout=2.0)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    total = 0.0
    seen: set[str] = set()
    lines = out.splitlines()[1:]
    for line in lines:
        cols = line.split()
        if len(cols) < 11:
            continue
        name = cols[0]
        if name in seen:
            continue
        seen.add(name)
        try:
            total += float(cols[6]) + float(cols[9])
        except (ValueError, IndexError):
            continue
    return total


def _read_net_total_bytes_linux() -> float | None:
    try:
        with open("/proc/net/dev", encoding="utf-8") as handle:
            handle.readline()
            handle.readline()
            total = 0.0
            for line in handle:
                if ":" not in line:
                    continue
                _, payload = line.split(":", 1)
                cols = payload.split()
                if len(cols) < 9:
                    continue
                try:
                    total += float(cols[0]) + float(cols[8])
                except ValueError:
                    continue
            return total
    except OSError:
        return None


def _read_net_mbps() -> float:
    bytes_now = _read_net_total_bytes_macos() or _read_net_total_bytes_linux()
    if bytes_now is None:
        return 0.0
    now = time.time()
    last_ts = _NET_CACHE["ts"]
    last_bytes = _NET_CACHE["bytes"]
    _NET_CACHE["ts"] = now
    _NET_CACHE["bytes"] = bytes_now
    if last_ts <= 0 or now <= last_ts:
        return 0.0
    delta_bytes = max(0.0, bytes_now - last_bytes)
    delta_seconds = max(0.001, now - last_ts)
    return (delta_bytes / delta_seconds) / 1024.0 / 1024.0


def read_sysinfo() -> dict[str, object]:
    return {
        "ok": True,
        "cpu_pct": round(_read_cpu_pct(), 1),
        "ram_pct": round(_read_ram_pct(), 1),
        "net_mbps": round(_read_net_mbps(), 2),
        "uptime_seconds": int(time.time() - SERVER_STARTED_AT),
        "platform": sys.platform,
    }


def parsed_path(raw_path: str) -> str:
    return urlparse(raw_path).path


def request_cookie(handler: SimpleHTTPRequestHandler, name: str) -> str | None:
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return None
    cookies = http.cookies.SimpleCookie(cookie_header)
    morsel = cookies.get(name)
    return morsel.value if morsel is not None else None


def set_cookie_header(handler: SimpleHTTPRequestHandler, name: str, value: str, max_age: int, http_only: bool = True) -> None:
    cookie = http.cookies.SimpleCookie()
    secure_cookies = os.environ.get("AIPS_SECURE_COOKIES", "0") == "1"
    same_site = os.environ.get("AIPS_COOKIE_SAMESITE", "None" if secure_cookies else "Lax")
    cookie[name] = value
    cookie[name]["path"] = "/"
    cookie[name]["max-age"] = str(max_age)
    cookie[name]["samesite"] = same_site
    if http_only:
        cookie[name]["httponly"] = True
    if secure_cookies:
        cookie[name]["secure"] = True
    handler.send_header("Set-Cookie", cookie.output(header="").strip())


def clear_cookie_header(handler: SimpleHTTPRequestHandler, name: str) -> None:
    set_cookie_header(handler, name, "", 0)


def request_client_ip(handler: SimpleHTTPRequestHandler) -> str:
    peer_ip = handler.client_address[0]
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return peer_ip
    trusted_proxy = peer.is_loopback
    trusted_ranges = os.environ.get("AIPS_TRUSTED_PROXY_RANGES", "")
    for raw_range in trusted_ranges.split(","):
        raw_range = raw_range.strip()
        if not raw_range:
            continue
        try:
            if peer in ipaddress.ip_network(raw_range, strict=False):
                trusted_proxy = True
                break
        except ValueError:
            continue
    if not trusted_proxy:
        return peer_ip
    forwarded = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    real_ip = handler.headers.get("X-Real-IP", "").strip()
    for candidate in [forwarded, real_ip]:
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return peer_ip


def allowed_cors_origin(handler: SimpleHTTPRequestHandler) -> str | None:
    origin = handler.headers.get("Origin")
    if not origin:
        return None
    configured = os.environ.get("AIPS_ALLOWED_ORIGINS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    if origin in allowed:
        return origin
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme in {"http", "https"} and parsed_origin.hostname in {"127.0.0.1", "localhost"}:
        return origin
    return None


def ensure_voter_id(handler: SimpleHTTPRequestHandler) -> tuple[str, bool]:
    voter_id = request_cookie(handler, VOTER_COOKIE)
    if voter_id:
        return voter_id, False
    import secrets
    return secrets.token_urlsafe(18), True


def is_admin(handler: SimpleHTTPRequestHandler) -> bool:
    return radio_state.validate_admin_session(ROOT, request_cookie(handler, ADMIN_COOKIE))


def admin_token(handler: SimpleHTTPRequestHandler) -> str | None:
    token = request_cookie(handler, ADMIN_COOKIE)
    return token if radio_state.validate_admin_session(ROOT, token) else None


def require_admin(handler: "ControlHandler") -> bool:
    if is_admin(handler):
        return True
    handler.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "Admin session required"})
    return False


class ControlHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def handle_one_request(self) -> None:
        # Browsers routinely abort range requests when seeking audio or skipping
        # HLS segments. SimpleHTTPRequestHandler doesn't catch those, which
        # produces a multi-line BrokenPipe traceback per disconnect. Treat the
        # connection-broken family as a benign one-line log message instead.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
            try:
                self.log_message("client disconnected: %s", self.requestline or "?")
            except Exception:
                pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        origin = allowed_cors_origin(self)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        if parsed_path(self.path).startswith("/api/"):
            self.send_response(HTTPStatus.NO_CONTENT)
            origin = allowed_cors_origin(self)
            if origin:
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if parsed_path(self.path).startswith("/api/admin/"):
            token = admin_token(self)
            if token:
                set_cookie_header(self, ADMIN_COOKIE, token, radio_state.SESSION_SECONDS, True)
        self.end_headers()
        _ = self.wfile.write(body)

    def send_json_with_cookies(self, status: HTTPStatus, payload: object, cookies: list[tuple[str, str, int, bool]]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value, max_age, http_only in cookies:
            set_cookie_header(self, name, value, max_age, http_only)
        self.end_headers()
        _ = self.wfile.write(body)

    def do_GET(self) -> None:
        path = parsed_path(self.path)
        if path.startswith("/public/radio-state/") or path.startswith("/.aips-state/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
            return
        if path == "/api/config":
            self.send_json(HTTPStatus.OK, {"ok": True, "backend_base_url": os.environ.get("AIPS_BACKEND_BASE_URL", ""), "media_base_url": os.environ.get("AIPS_MEDIA_BASE_URL", "")})
            return
        if path == "/api/llm-status":
            self.send_json(HTTPStatus.OK, check_llm_status())
            return
        if path == "/api/radio-status":
            self.send_json(HTTPStatus.OK, radio_window_status())
            return
        if path == "/api/sysinfo":
            self.send_json(HTTPStatus.OK, read_sysinfo())
            return
        if path == "/api/vote-round":
            self.send_json(HTTPStatus.OK, radio_state.public_vote_round(ROOT, request_cookie(self, VOTER_COOKIE)))
            return
        if path == "/api/archive":
            self.send_json(HTTPStatus.OK, radio_state.archive_payload(ROOT))
            return
        if path == "/api/fallback":
            latest = radio_state.latest_archive(ROOT)
            fallback = read_fallback_mode()
            forced = fallback.get("enabled") is True
            mode = "archive" if latest and (forced or latest) else "initializing"
            self.send_json(HTTPStatus.OK, {"ok": True, "mode": mode, "forced": forced, "recording": latest.get("recording") if latest else None, "latest": latest})
            return
        if path == "/api/admin/session":
            self.send_json(HTTPStatus.OK, {"ok": True, "admin": is_admin(self)})
            return
        if path == "/api/admin/suggestions":
            if not require_admin(self):
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "suggestions": radio_state.read_suggestions(ROOT)})
            return
        if path == "/api/admin/collapse":
            if not require_admin(self):
                return
            self.send_json(HTTPStatus.OK, radio_state.collapse_metrics(ROOT))
            return
        if path == "/api/admin/override":
            if not require_admin(self):
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "override": read_admin_override()})
            return
        if path == "/api/admin/fallback":
            if not require_admin(self):
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "fallback": read_fallback_mode()})
            return
        if path == "/api/admin/health":
            if not require_admin(self):
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "sysinfo": read_sysinfo(), "llm": check_llm_status()})
            return
        if path == "/api/preset-modes":
            preset_modes = read_preset_modes()
            if preset_modes is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "preset-modes.json not found"})
                return
            preset_modes["ok"] = True
            self.send_json(HTTPStatus.OK, preset_modes)
            return
        if path in {"/admin", "/admin/"}:
            self.path = "/web/new/index.html"
        if path == "/":
            self.path = "/web/"
        super().do_GET()

    def do_POST(self) -> None:
        try:
            path = parsed_path(self.path)
            payload = read_request_json(self)
            if path == "/api/admin/login":
                password = payload.get("password")
                if not isinstance(password, str):
                    raise ValueError("password must be a string")
                token = radio_state.create_admin_session(ROOT, password)
                self.send_json_with_cookies(HTTPStatus.OK, {"ok": True, "admin": True, "expires_in_seconds": radio_state.SESSION_SECONDS}, [(ADMIN_COOKIE, token, radio_state.SESSION_SECONDS, True)])
                return
            if path == "/api/admin/logout":
                radio_state.destroy_admin_session(ROOT, request_cookie(self, ADMIN_COOKIE))
                self.send_json_with_cookies(HTTPStatus.OK, {"ok": True, "admin": False}, [(ADMIN_COOKIE, "", 0, True)])
                return
            if path == "/api/vote":
                voter_id, is_new = ensure_voter_id(self)
                result = radio_state.record_vote(ROOT, voter_id, payload, request_client_ip(self))
                cookies = [(VOTER_COOKIE, voter_id, 60 * 60 * 24 * 365, True)] if is_new else []
                self.send_json_with_cookies(HTTPStatus.OK, result, cookies)
                return
            if path == "/api/suggestions":
                text = payload.get("text")
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
                suggestion = radio_state.add_suggestion(ROOT, text, request_client_ip(self))
                self.send_json(HTTPStatus.OK, {"ok": True, "suggestion": {key: suggestion[key] for key in ["id", "status", "reason", "created_at"]}})
                return
            if path == "/api/admin/vote-round":
                if not require_admin(self):
                    return
                raw_options = payload.get("options")
                if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 4:
                    raise ValueError("Vote round needs 2 to 4 options")
                current = radio_state.read_vote_round(ROOT)
                radio_state.close_round_for_summary(ROOT, current)
                current.update({"id": str(payload.get("id") or f"round-{int(time.time())}"), "status": "active", "options": [radio_state.clean_option(cast(dict[str, Any], item)) for item in raw_options if isinstance(item, dict)], "role_options": validate_role_options(payload.get("role_options")), "votes": {}, "created_at": utc_now(), "closed_snapshot": None})
                self.send_json(HTTPStatus.OK, {"ok": True, "round": radio_state.save_vote_round(ROOT, current)})
                return
            if path == "/api/admin/suggestions":
                if not require_admin(self):
                    return
                suggestion_id = payload.get("id")
                action = payload.get("action")
                if not isinstance(suggestion_id, str) or not isinstance(action, str):
                    raise ValueError("id and action are required")
                self.send_json(HTTPStatus.OK, {"ok": True, "suggestion": radio_state.update_suggestion(ROOT, suggestion_id, action)})
                return
            if path == "/api/admin/suggestions/promote":
                if not require_admin(self):
                    return
                suggestion_id = payload.get("id")
                if not isinstance(suggestion_id, str):
                    raise ValueError("id is required")
                label = payload.get("label") if isinstance(payload.get("label"), str) else None
                option = radio_state.promote_suggestion_to_option(ROOT, suggestion_id, label)
                current = radio_state.read_vote_round(ROOT)
                options = current.setdefault("options", [])
                if not isinstance(options, list):
                    options = []
                    current["options"] = options
                if len(options) >= 4:
                    raise ValueError("Current round already has 4 options; create a new curated round or remove one first")
                options.append(option)
                self.send_json(HTTPStatus.OK, {"ok": True, "option": option, "round": radio_state.save_vote_round(ROOT, current)})
                return
            if path == "/api/admin/override":
                if not require_admin(self):
                    return
                self.send_json(HTTPStatus.OK, {"ok": True, "override": write_admin_override(payload)})
                return
            if path == "/api/admin/fallback":
                if not require_admin(self):
                    return
                enabled = payload.get("enabled") is True
                self.send_json(HTTPStatus.OK, {"ok": True, "fallback": write_fallback_mode(enabled)})
                return
            if path == "/api/personas":
                personas = validate_personas(payload)
                write_json(PERSONAS_PATH, personas)
                self.send_json(HTTPStatus.OK, {"ok": True, "saved_at": utc_now(), "personas": personas})
                return
            if path == "/api/live-control":
                live_control = validate_live_control(payload)
                live_control = attach_conductor_status(live_control)
                write_json(LIVE_CONTROL_PATH, live_control)
                self.send_json(HTTPStatus.OK, {"ok": True, "live_control": live_control})
                return
            if path == "/api/preset-modes":
                preset_modes = validate_preset_modes(payload)
                write_json(PRESET_MODES_PATH, preset_modes)
                self.send_json(HTTPStatus.OK, {"ok": True, "preset_modes": preset_modes})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API route"})
        except (json.JSONDecodeError, ValueError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the AI ensemble web page with writable control APIs.")
    _ = parser.add_argument("--host", default="127.0.0.1")
    _ = parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ControlHandler)
    print(f"Serving AI ensemble controls at http://{args.host}:{args.port}/web/")
    server.serve_forever()


if __name__ == "__main__":
    main()
