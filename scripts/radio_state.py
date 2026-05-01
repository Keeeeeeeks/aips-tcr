#!/usr/bin/env python3
"""Persistent radio-state helpers for voting, admin, suggestions, and collapse logs."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast


ROLE_KEYS = {"percussion", "bass", "piano", "lead", "texture"}
SESSION_SECONDS = 8 * 60 * 60
VOTE_IP_WINDOW_SECONDS = 60
VOTE_IP_LIMIT = 8
SUGGESTION_IP_WINDOW_SECONDS = 10 * 60
SUGGESTION_IP_LIMIT = 6


class RadioPaths(TypedDict):
    root: Path
    public: Path
    state_dir: Path
    archive_index: Path


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def paths(root: Path) -> RadioPaths:
    public = root / "public"
    state_root = Path(os.environ.get("AIPS_STATE_DIR", root / ".aips-state" / "radio-state"))
    return {
        "root": root,
        "public": public,
        "state_dir": state_root,
        "archive_index": public / "archive" / "index.json",
    }


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return fallback


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    _ = temp_path.write_text(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


def default_vote_round(public: Path) -> dict[str, Any]:
    presets = read_json(public / "preset-modes.json", {})
    profiles = presets.get("profiles") if isinstance(presets, dict) else None
    options: list[dict[str, Any]] = []
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if profile_id == "none" or not isinstance(profile, dict):
                continue
            options.append(
                {
                    "id": str(profile_id),
                    "label": str(profile.get("label") or profile_id),
                    "prompt": str(profile.get("live_prompt") or ""),
                    "tempo_bpm": profile.get("tempo_bpm", 92),
                    "key": str(profile.get("key") or "A minor"),
                    "psychosis_level": profile.get("psychosis_level", 0.25),
                }
            )
            if len(options) >= 4:
                break
    if not options:
        options = [
            {"id": "spacious", "label": "Spacious", "prompt": "Keep the band spacious, late-night, and coherent.", "tempo_bpm": 92, "key": "A minor", "psychosis_level": 0.25},
            {"id": "frantic", "label": "Frantic", "prompt": "150 bpm, frantic breakcore pressure, distorted chopped breaks, unstable but coherent.", "tempo_bpm": 150, "key": "A minor", "psychosis_level": 0.72},
        ]
    return {
        "id": "round-default",
        "status": "active",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "options": options[:4],
        "role_options": {role: [] for role in sorted(ROLE_KEYS)},
        "votes": {},
        "closed_snapshot": None,
    }


def vote_round_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "vote-round.json"


def read_vote_round(root: Path) -> dict[str, Any]:
    path = vote_round_path(root)
    payload = read_json(path, None)
    if isinstance(payload, dict) and isinstance(payload.get("options"), list):
        return cast(dict[str, Any], payload)
    payload = default_vote_round(paths(root)["public"])
    write_json(path, payload)
    return payload


def save_vote_round(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload["updated_at"] = utc_now()
    write_json(vote_round_path(root), payload)
    return payload


def rate_limit_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "rate-limits.json"


def check_rate_limit(root: Path, scope: str, ip: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    ip_hash = hash_ip(ip)
    payload = read_json(rate_limit_path(root), {})
    limits = payload if isinstance(payload, dict) else {}
    scope_limits = limits.get(scope)
    if not isinstance(scope_limits, dict):
        scope_limits = {}
    recent = [float(ts) for ts in scope_limits.get(ip_hash, []) if isinstance(ts, int | float) and now - float(ts) < window_seconds]
    if len(recent) >= limit:
        raise ValueError("Rate limit exceeded; please wait before trying again")
    recent.append(now)
    scope_limits[ip_hash] = recent
    limits[scope] = scope_limits
    write_json(rate_limit_path(root), limits)


def clean_option(raw: dict[str, Any]) -> dict[str, Any]:
    option_id = str(raw.get("id") or raw.get("label") or secrets.token_hex(4)).strip().lower()
    option_id = re.sub(r"[^a-z0-9_-]+", "-", option_id).strip("-") or secrets.token_hex(4)
    label = str(raw.get("label") or option_id).strip()[:80]
    prompt = " ".join(str(raw.get("prompt") or "").strip().split())[:800]
    if not label or not prompt:
        raise ValueError("Each vote option needs a label and prompt")
    tempo_raw = raw.get("tempo_bpm", 92)
    tempo = int(max(60, min(220, int(tempo_raw)))) if isinstance(tempo_raw, int | float | str) and str(tempo_raw).isdigit() else 92
    psychosis_raw = raw.get("psychosis_level", 0.25)
    psychosis = max(0.0, min(1.0, float(psychosis_raw))) if isinstance(psychosis_raw, int | float) else 0.25
    option = {"id": option_id, "label": label, "prompt": prompt, "tempo_bpm": tempo, "key": str(raw.get("key") or "A minor")[:40], "psychosis_level": psychosis}
    time_signature = raw.get("time_signature")
    if isinstance(time_signature, str) and time_signature in {"4/4", "3/4", "6/8", "5/4", "7/8"}:
        option["time_signature"] = time_signature
    return option


def vote_tally(round_payload: dict[str, Any]) -> dict[str, Any]:
    votes = round_payload.get("votes")
    options = round_payload.get("options")
    option_ids = [str(option.get("id")) for option in options if isinstance(option, dict)] if isinstance(options, list) else []
    counts = {option_id: 0 for option_id in option_ids}
    role_counts: dict[str, dict[str, int]] = {role: {} for role in sorted(ROLE_KEYS)}
    if isinstance(votes, dict):
        for vote in votes.values():
            if not isinstance(vote, dict):
                continue
            option_id = str(vote.get("option_id") or "")
            if option_id in counts:
                counts[option_id] += 1
            role_votes = vote.get("role_votes")
            if isinstance(role_votes, dict):
                for role, value in role_votes.items():
                    if role not in ROLE_KEYS or not isinstance(value, str):
                        continue
                    role_counts.setdefault(role, {})[value] = role_counts.setdefault(role, {}).get(value, 0) + 1
    winner = max(counts, key=lambda key: (counts[key], -option_ids.index(key))) if counts else None
    role_winners: dict[str, str] = {}
    for role, counts_for_role in role_counts.items():
        if counts_for_role:
            role_winners[role] = max(counts_for_role, key=lambda key: (counts_for_role[key], key))
    unique_voters = len(votes) if isinstance(votes, dict) else 0
    unique_ip_hashes = len({str(vote.get("ip_hash")) for vote in votes.values() if isinstance(vote, dict) and vote.get("ip_hash")}) if isinstance(votes, dict) else 0
    return {"counts": counts, "winner": winner, "role_counts": role_counts, "role_winners": role_winners, "total_votes": sum(counts.values()), "unique_voters": unique_voters, "unique_ip_hashes": unique_ip_hashes}


def current_winning_option(root: Path) -> dict[str, Any] | None:
    round_payload = read_vote_round(root)
    tally = vote_tally(round_payload)
    winner = tally.get("winner")
    options = round_payload.get("options")
    if not isinstance(winner, str) or not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, dict) and option.get("id") == winner:
            result = dict(option)
            result["vote_snapshot"] = tally
            result["role_winners"] = tally.get("role_winners", {})
            return result
    return None


def record_vote(root: Path, voter_id: str, payload: dict[str, Any], ip: str) -> dict[str, Any]:
    check_rate_limit(root, "vote", ip, VOTE_IP_LIMIT, VOTE_IP_WINDOW_SECONDS)
    round_payload = read_vote_round(root)
    if round_payload.get("status") != "active":
        raise ValueError("Voting round is not active")
    votes = round_payload.setdefault("votes", {})
    if not isinstance(votes, dict):
        votes = {}
        round_payload["votes"] = votes
    if voter_id in votes:
        raise ValueError("This browser already voted in the active round")
    option_id = str(payload.get("option_id") or "")
    options = round_payload.get("options")
    valid_options = {str(option.get("id")) for option in options if isinstance(option, dict)} if isinstance(options, list) else set()
    if option_id not in valid_options:
        raise ValueError("Unknown vote option")
    role_votes: dict[str, str] = {}
    raw_role_votes = payload.get("role_votes")
    role_options = round_payload.get("role_options")
    if isinstance(raw_role_votes, dict):
        for role, value in raw_role_votes.items():
            if role not in ROLE_KEYS or not isinstance(value, str):
                continue
            allowed_values: set[str] = set()
            if isinstance(role_options, dict):
                raw_allowed = role_options.get(role)
                if isinstance(raw_allowed, list):
                    for option in raw_allowed:
                        if isinstance(option, dict) and isinstance(option.get("id"), str):
                            allowed_values.add(option["id"])
                        elif isinstance(option, str):
                            allowed_values.add(option)
            if allowed_values and value not in allowed_values:
                raise ValueError(f"Unknown role vote option for {role}")
            role_votes[role] = value[:80]
    votes[voter_id] = {"option_id": option_id, "role_votes": role_votes, "created_at": utc_now(), "ip_hash": hash_ip(ip)}
    save_vote_round(root, round_payload)
    append_behavior_event(root, "vote", {"option_id": option_id, "role_votes": role_votes})
    return public_vote_round(root, voter_id)


def public_vote_round(root: Path, voter_id: str | None = None) -> dict[str, Any]:
    round_payload = read_vote_round(root)
    votes = round_payload.get("votes")
    my_vote = votes.get(voter_id) if isinstance(votes, dict) and voter_id else None
    return {"ok": True, "round": {key: value for key, value in round_payload.items() if key != "votes"}, "tally": vote_tally(round_payload), "my_vote": my_vote, "audible_eta": vote_audible_eta(root)}


def vote_audible_eta(root: Path) -> dict[str, Any]:
    status = read_json(paths(root)["public"] / "conductor-status.json", {})
    if not isinstance(status, dict) or status.get("delivery_status") != "segment_conductor_running":
        return {"available": False, "message": "Winner applies when the conductor is running; stream initializing."}
    next_seconds = status.get("next_section_eta_seconds")
    buffered_sections = status.get("buffered_sections")
    prompt_sections = status.get("prompt_sections_until_heard")
    sections_until_audible = prompt_sections if isinstance(prompt_sections, int) else buffered_sections if isinstance(buffered_sections, int) else None
    if isinstance(next_seconds, int | float):
        base = f"current winner can be applied at the next section boundary in about {int(next_seconds)}s"
    else:
        base = "current winner can be applied at the next section boundary"
    if isinstance(sections_until_audible, int):
        base += f" and heard after roughly {max(1, sections_until_audible)} buffered section(s)"
    return {"available": True, "next_section_eta_seconds": next_seconds, "sections_until_audible": sections_until_audible, "message": base}


def hash_ip(ip: str) -> str:
    salt = os.environ.get("RADIO_STATE_SALT", "aips-radio-state")
    return hmac.new(salt.encode(), ip.encode(), "sha256").hexdigest()[:16]


def admin_secret() -> str | None:
    return os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_SECRET")


def sessions_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "admin-sessions.json"


def read_sessions(root: Path) -> dict[str, Any]:
    payload = read_json(sessions_path(root), {})
    return cast(dict[str, Any], payload if isinstance(payload, dict) else {})


def create_admin_session(root: Path, password: str) -> str:
    secret = admin_secret()
    if not secret or not hmac.compare_digest(password, secret):
        raise ValueError("Invalid admin password")
    token = secrets.token_urlsafe(32)
    now = time.time()
    sessions = read_sessions(root)
    sessions[token] = {"created_at": now, "last_seen": now, "expires_at": now + SESSION_SECONDS}
    write_json(sessions_path(root), sessions)
    return token


def validate_admin_session(root: Path, token: str | None) -> bool:
    if not token:
        return False
    sessions = read_sessions(root)
    session = sessions.get(token)
    now = time.time()
    if not isinstance(session, dict) or float(session.get("expires_at", 0)) < now:
        if token in sessions:
            del sessions[token]
            write_json(sessions_path(root), sessions)
        return False
    session["last_seen"] = now
    session["expires_at"] = now + SESSION_SECONDS
    sessions[token] = session
    write_json(sessions_path(root), sessions)
    return True


def destroy_admin_session(root: Path, token: str | None) -> None:
    if not token:
        return
    sessions = read_sessions(root)
    if token in sessions:
        del sessions[token]
        write_json(sessions_path(root), sessions)


def suggestion_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "suggestions.json"


def read_suggestions(root: Path) -> list[dict[str, Any]]:
    payload = read_json(suggestion_path(root), [])
    return cast(list[dict[str, Any]], payload if isinstance(payload, list) else [])


BLOCKED_PATTERNS = [
    r"ignore (all )?(previous|prior|system)",
    r"system prompt",
    r"reveal.*(secret|key|password|prompt)",
    r"api[_ -]?key",
    r"admin",
    r"exact lyrics",
    r"verbatim",
    r"impersonat(e|ing)",
    r"kill yourself",
    r"hate speech",
]


def classify_suggestion(text: str) -> tuple[str, str]:
    lowered = text.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered):
            return "quarantined", f"Matched refusal pattern: {pattern}"
    if len(text.strip()) < 8:
        return "rejected", "Suggestion is too short"
    return "pending", "Awaiting admin review"


def add_suggestion(root: Path, text: str, ip: str) -> dict[str, Any]:
    check_rate_limit(root, "suggestion", ip, SUGGESTION_IP_LIMIT, SUGGESTION_IP_WINDOW_SECONDS)
    clean_text = " ".join(text.strip().split())[:800]
    status, reason = classify_suggestion(clean_text)
    suggestions = read_suggestions(root)
    item = {"id": secrets.token_hex(8), "text": clean_text, "status": status, "reason": reason, "created_at": utc_now(), "ip_hash": hash_ip(ip)}
    suggestions.insert(0, item)
    write_json(suggestion_path(root), suggestions)
    append_behavior_event(root, "suggestion", {"status": status})
    return item


def approved_suggestions_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "approved-suggestions.json"


def read_approved_suggestions(root: Path) -> list[dict[str, Any]]:
    payload = read_json(approved_suggestions_path(root), [])
    return cast(list[dict[str, Any]], payload if isinstance(payload, list) else [])


def update_suggestion(root: Path, suggestion_id: str, action: str) -> dict[str, Any]:
    suggestions = read_suggestions(root)
    for item in suggestions:
        if item.get("id") == suggestion_id:
            if action not in {"approved", "rejected", "pending"}:
                raise ValueError("Unknown suggestion action")
            item["status"] = action
            item["reviewed_at"] = utc_now()
            write_json(suggestion_path(root), suggestions)
            if action == "approved":
                approved = read_approved_suggestions(root)
                if not any(existing.get("id") == item.get("id") for existing in approved):
                    approved.insert(0, {**item, "approved_at": item["reviewed_at"], "promoted_at": None})
                    write_json(approved_suggestions_path(root), approved)
            append_behavior_event(root, "suggestion_review", {"status": action})
            return item
    raise ValueError("Suggestion not found")


def promote_suggestion_to_option(root: Path, suggestion_id: str, label: str | None = None) -> dict[str, Any]:
    approved = read_approved_suggestions(root)
    selected: dict[str, Any] | None = None
    for item in approved:
        if item.get("id") == suggestion_id and item.get("status") == "approved":
            selected = item
            break
    if selected is None:
        raise ValueError("Approved suggestion not found")
    option = clean_option({"id": f"suggestion-{suggestion_id[:8]}", "label": label or selected.get("text", "Listener suggestion"), "prompt": selected.get("text", "")})
    selected["promoted_at"] = utc_now()
    selected["promoted_option_id"] = option["id"]
    write_json(approved_suggestions_path(root), approved)
    append_behavior_event(root, "suggestion_promoted", {"suggestion_id": suggestion_id, "option_id": option["id"]})
    return option


def round_summary(round_payload: dict[str, Any]) -> dict[str, Any]:
    tally = vote_tally(round_payload)
    return {
        "round_id": round_payload.get("id"),
        "created_at": round_payload.get("created_at"),
        "closed_at": utc_now(),
        "vote_count": tally.get("total_votes", 0),
        "unique_voter_count": tally.get("unique_voters", 0),
        "unique_ip_hash_count": tally.get("unique_ip_hashes", 0),
        "winning_option": tally.get("winner"),
        "role_winners": tally.get("role_winners", {}),
    }


def close_round_for_summary(root: Path, round_payload: dict[str, Any]) -> None:
    if round_payload.get("id"):
        append_behavior_event(root, "round_summary", round_summary(round_payload))


def behavior_path(root: Path) -> Path:
    return paths(root)["state_dir"] / "behavior-log.json"


def append_behavior_event(root: Path, event_type: str, payload: dict[str, Any]) -> None:
    events = read_json(behavior_path(root), [])
    if not isinstance(events, list):
        events = []
    events.append({"type": event_type, "created_at": utc_now(), **payload})
    write_json(behavior_path(root), events[-2000:])


def collapse_metrics(root: Path) -> dict[str, Any]:
    events = read_json(behavior_path(root), [])
    if not isinstance(events, list):
        events = []
    votes = [event for event in events if isinstance(event, dict) and event.get("type") == "vote"]
    suggestions = [event for event in events if isinstance(event, dict) and event.get("type") == "suggestion"]
    suggestion_reviews = [event for event in events if isinstance(event, dict) and event.get("type") == "suggestion_review"]
    round_summaries = [event for event in events if isinstance(event, dict) and event.get("type") == "round_summary"]
    last_event = events[-1] if events else None
    inactivity_seconds = 0
    if isinstance(last_event, dict) and isinstance(last_event.get("created_at"), str):
        try:
            last_ts = datetime.fromisoformat(last_event["created_at"].replace("Z", "+00:00")).timestamp()
            inactivity_seconds = int(max(0, time.time() - last_ts))
        except ValueError:
            inactivity_seconds = 0
    recent_vote_options = [str(event.get("option_id")) for event in votes[-10:] if isinstance(event, dict)]
    convergence_streak = 0
    if recent_vote_options:
        latest = recent_vote_options[-1]
        for option in reversed(recent_vote_options):
            if option == latest:
                convergence_streak += 1
            else:
                break
    current_round = read_vote_round(root)
    current_tally = vote_tally(current_round)
    recent_winners = [str(event.get("winning_option")) for event in round_summaries[-10:] if event.get("winning_option")]
    repeated_winner_streak = 0
    if recent_winners:
        latest_winner = recent_winners[-1]
        for winner in reversed(recent_winners):
            if winner == latest_winner:
                repeated_winner_streak += 1
            else:
                break
    approved_count = len([event for event in suggestion_reviews if event.get("status") == "approved"])
    return {
        "ok": True,
        "vote_frequency": len(votes),
        "suggestion_rate": len(suggestions),
        "approved_suggestion_count": approved_count,
        "inactivity_seconds": inactivity_seconds,
        "convergence_streak": convergence_streak,
        "repeated_winning_option_streak": repeated_winner_streak,
        "current_round": {
            "round_id": current_round.get("id"),
            "vote_count": current_tally.get("total_votes", 0),
            "unique_voter_count": current_tally.get("unique_voters", 0),
            "unique_ip_hash_count": current_tally.get("unique_ip_hashes", 0),
            "winning_option": current_tally.get("winner"),
            "role_winners": current_tally.get("role_winners", {}),
        },
        "round_summaries": round_summaries[-12:],
        "interpretation": "behavioral/artistic signal only; not a scientific or diagnostic measure",
    }


def latest_archive(root: Path) -> dict[str, Any] | None:
    index = read_json(paths(root)["archive_index"], [])
    if isinstance(index, list) and index and isinstance(index[0], dict):
        return cast(dict[str, Any], index[0])
    return None


def archive_payload(root: Path) -> dict[str, Any]:
    index = read_json(paths(root)["archive_index"], [])
    if not isinstance(index, list):
        index = []
    return {"ok": True, "latest": latest_archive(root), "entries": index}
