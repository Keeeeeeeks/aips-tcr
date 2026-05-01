# Phase 1 Implementation Plan: Public Radio Deployment

Date: 2026-05-01
Status: Planned
Design source: `docs/superpowers/specs/2026-05-01-aips-radio-deployment-design.md`

## Goal

Ship one public AIPS radio station with Vercel-hosted frontend, Hetzner-hosted backend/conductor/media, anonymous fixed-menu voting, moderated suggestions, admin password auth, permanent public archives, and fallback playback to the latest archived MP3.

## Acceptance Criteria

Phase 1 is complete when:

1. The public frontend can be served statically and configured to talk to a Hetzner backend URL.
2. Hetzner backend serves API state, admin auth, vote rounds, suggestions, archive metadata, and conductor health.
3. HLS media is served through nginx or an equivalent static file server from the conductor output directory.
4. Anonymous cookie voting allows one vote per active round, with IP/rate-limit protection.
5. Admin password auth uses an environment variable and issues an HttpOnly session cookie with 8-hour inactivity expiry and logout.
6. Listener suggestions are stored pending admin approval and never reach the conductor directly.
7. The conductor applies fixed-menu winners and role sub-votes at section boundaries.
8. The archive preserves MP3, MIDI, applied prompts/style config, role bundles, vote snapshot, timing metadata, render engine, and soundfont metadata.
9. The public archive page can browse prior sessions.
10. The player falls back to the latest archived MP3 on HLS 404, parse failure, or timeout; before the first archive exists it shows “stream initializing.”
11. The UI displays when the current round's winner becomes audible.
12. No `.env`, API keys, admin secrets, generated cookies, private credentials, or legally ambiguous soundfonts are committed.

## Implementation Steps

### 1. Split deploy configuration from local paths

- Add a frontend runtime config pattern for backend base URL and media base URL.
- Keep local defaults pointing at the existing `control_server.py` layout.
- Add `.env.example` documenting safe variables only: backend URL, media URL, admin password variable name, OpenAI-compatible variables, soundfont path, archive path.
- Update README deployment notes after the implementation is working.

### 2. Add persistent backend state files

- Introduce backend JSON stores or a lightweight SQLite database for:
  - active voting round,
  - votes,
  - anonymous voter cookies,
  - pending suggestions,
  - approved suggestions,
  - admin sessions,
  - archive index.
- Prefer SQLite if concurrent writes become risky; otherwise maintain atomic JSON writes using existing `write_json` pattern.
- Preserve compatibility with existing `public/live-control.json`, `public/preset-modes.json`, `public/conductor-status.json`, and `public/current-session.json` during the transition.

### 3. Implement admin password sessions

- Add `POST /api/admin/login` that validates `ADMIN_PASSWORD` or `ADMIN_SECRET` using constant-time comparison.
- Issue an HttpOnly, SameSite, Secure-in-production session cookie.
- Store server-side session expiry and last-used timestamp.
- Add `POST /api/admin/logout`.
- Protect admin-only endpoints for vote-round curation, suggestion approval, override, emergency fallback, and health details.

### 4. Implement voting rounds

- Add endpoints:
  - `GET /api/vote-round` for current options, tally, current listener vote, and audible ETA.
  - `POST /api/vote` for global style vote and optional role sub-votes.
  - `POST /api/admin/vote-round` for admin-curated fixed-menu options.
- Set/refresh an anonymous voter cookie on first vote.
- Enforce one vote per cookie per round and rate-limit by IP.
- Record vote snapshots when a round closes.

### 5. Implement moderated suggestions

- Add `POST /api/suggestions` for listener submissions.
- Store suggestions as pending only.
- Add refusal checks for prompt injection, operational instructions, secret/system prompt requests, direct copyrighted-lyrics requests, direct replication requests, unsafe content, and impersonation.
- Add admin endpoints to approve/reject suggestions and promote approved suggestions into future fixed-menu options.

### 6. Wire conductor to voting state

- Teach `segment_conductor.py` to read the active/closed vote winner at section boundaries.
- Convert winning global style into `live_control`/preset-mode state.
- Apply role sub-votes only inside the global tempo/key/form envelope.
- Keep admin override backstage and higher priority than votes.
- Preserve the existing heuristic fallback if LLM calls fail.

### 7. Preserve permanent archives

- Stop treating current-session trimming as deletion of historical artifacts.
- Keep temporary HLS and WAV cleanup for live operation.
- On session or archive boundary, persist MP3, MIDI, prompts/style config, role bundles, vote snapshot, timestamps, render engine, and soundfont metadata.
- Expose `GET /api/archive` and static archive artifact URLs.

### 8. Frontend updates

- Update the public page with:
  - live player using backend/media config,
  - vote panel,
  - role sub-vote controls,
  - suggestion form,
  - audible ETA copy,
  - fallback/initializing state,
  - archive browser entry points.
- Add a backstage admin page or modal with login, vote-round curation, suggestion moderation, override, fallback toggle, and health.
- Keep the current Liquid Glass/Y2K Aero style.

### 9. Hetzner deployment assets

- Add example systemd unit files for:
  - backend control API,
  - segment conductor.
- Add example nginx config for HLS/static media and reverse proxy to the backend API if needed.
- Document expected directories for stream output, archive storage, logs, and soundfonts.

## Unit and Integration Tests

- Admin auth rejects missing/wrong password and accepts the env password.
- Admin session cookie is HttpOnly and expires after inactivity.
- Vote endpoint creates one anonymous cookie, accepts one vote per round, and rejects duplicate/rate-limited attempts.
- Vote tally is deterministic and produces a winning option.
- Suggestions with prompt-injection markers or unsafe requests are quarantined/rejected.
- Admin approval can promote a suggestion into a future menu option.
- Conductor state selection respects admin override over vote winner.
- Archive writer preserves required artifact metadata and never deletes archived sessions during live cleanup.
- Fallback selection returns latest archived MP3 when HLS is unavailable.

## End-to-End Testing

Run these E2E flows locally first, then on Hetzner/Vercel staging.

### E2E 1: Cold start with no archive

1. Start backend without conductor and with an empty archive.
2. Open frontend.
3. Verify live player shows “stream initializing.”
4. Verify no MP3 fallback request loops forever.

### E2E 2: Live conductor playback

1. Start backend, conductor, and static media server.
2. Open frontend and click Start live audio.
3. Verify HLS playlist loads and audio plays.
4. Verify conductor health, current style, and next audible ETA appear.

### E2E 3: Voting applies to a future section

1. Admin creates a round with 2-4 fixed options.
2. Anonymous listener votes for one global style and one role sub-vote.
3. Verify cookie is set and duplicate votes in the same round are blocked.
4. Wait for the next section boundary.
5. Verify `live-control`/conductor state reflects the winning option.
6. Verify UI shows when the winner becomes audible.

### E2E 4: Suggestion moderation

1. Submit a safe listener suggestion.
2. Submit a prompt-injection suggestion.
3. Verify safe suggestion appears pending for admin.
4. Verify unsafe suggestion is rejected or quarantined.
5. Admin approves safe suggestion and promotes it into a future vote menu.

### E2E 5: Admin login and override

1. Generate admin password with `openssl rand -base64 32` and set env var.
2. Log in through admin UI.
3. Verify HttpOnly session cookie exists and admin controls unlock.
4. Set a backstage override.
5. Verify conductor applies override before vote winner.
6. Logout and verify admin endpoints reject the old session.

### E2E 6: Archive and fallback

1. Let conductor generate enough audio to create an archive entry.
2. Verify archive page lists the session.
3. Verify MP3, MIDI, prompts/style config, role bundles, vote snapshot, timing metadata, render engine, and soundfont metadata are present.
4. Stop conductor or make HLS unavailable.
5. Reload frontend and verify playback falls back to the latest archived MP3 loop.

## Manual QA Evidence to Capture

- Screenshot or browser log of live HLS playback.
- JSON response from `GET /api/vote-round` before and after a vote.
- JSON archive entry showing all required artifacts.
- Admin login response showing session cookie headers without exposing the secret.
- Browser behavior for first-run no-archive and HLS-failure fallback.

## Completion Notes

Do not deploy soundfonts or secrets through the public repo. Do not implement Phase 2 music vocabulary or Phase 3 About/collapse metrics in Phase 1 except where Phase 1 needs legal disclaimer surfaces and archive metadata placeholders.
