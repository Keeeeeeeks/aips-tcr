# The Chinese Room Radio / AI Ensemble

An open-source generative radio experiment by Resoworks for the AIPS Summit. The project is a meditation on the Chinese Room and on LLM systems as procedural imitations of understanding: one continuous symbolic MIDI ensemble stream, shaped by prompts, fixed-menu votes, and role-agent bundles.

## What it builds

- Seeded symbolic events for percussion, bass, piano, lead, and texture roles, with light variation across phrases.
- `public/stream/ensemble.mid` as the MIDI artifact.
- `public/stream/ensemble.wav` rendered from parsed MIDI events.
- `public/recordings/dummy-live-recording.mp3` as the saved recording artifact.
- `public/archive/<run-id>/` as a browsable archive of each generated run.
- `public/archive/index.json` as the archive index used by the web page.
- `public/current-session.json` plus `public/sessions/<session-id>/current-stream.mp3` as the active stream's growing session recording.
- `public/personas.json` as the editable persona/prompt source for the five roles.
- `public/live-control.json` as the contributor's current vibe instruction for the next generated form.
- `public/stream/index.m3u8` plus `.ts` segments for rolling live-style HLS playback.
- `public/stream/state.json` for the simple visual role cards.
- Enhanced audio rendering via stereo internal synth plus FFmpeg EQ/compression/echo/limiting, with optional FluidSynth soundfont support.
- `web/index.html` as the listener page.
- `scripts/control_server.py` as the local writable server for saving personas and live-control prompts.
- `scripts/segment_conductor.py` as the section-loop conductor for prompt-reactive streaming.
- `scripts/radio_state.py` as the persistent voting, suggestion, admin-session, archive-fallback, and behavior-metrics state layer.
- `public/music-config.json` as the deploy-visible schema for safe meters, style envelope limits, instrument pools, and soundfont pack metadata.
- `web/new/index.html` as the current Liquid Glass / Y2K Aero public interface.

## Requirements

- Python 3
- FFmpeg on `PATH`
- Optional FluidSynth for `.sf2` / `.sf3` soundfont rendering

## Generate the dummy stream

```bash
python3 scripts/generate_dummy_stream.py
```

By default this creates a finite QA version of the rolling playlist. To run FFmpeg continuously, pass `--live-duration-seconds 0`.

The generator also records the active stream session into one growing MP3 assembled from internal chunks. By default it updates every five minutes. Use a stable session id when you want restarts to append to the same session:

```bash
python3 scripts/generate_dummy_stream.py --live-duration-seconds 0 --session-id summit-demo
```

For faster local QA, shorten the chunk interval:

```bash
python3 scripts/generate_dummy_stream.py --live-duration-seconds 20 --session-id qa --session-chunk-seconds 5
```

Each run now creates a fresh musical variation by default. To make a run reproducible, pass a seed:

```bash
python3 scripts/generate_dummy_stream.py --seed 42
```

To make the stream take longer to repeat, increase the composed form length:

```bash
python3 scripts/generate_dummy_stream.py --bars 256 --live-duration-seconds 0 --session-id summit-demo
```

## Run the prompt-reactive conductor

For the live demo path, run the writable control server in one terminal:

```bash
python3 scripts/control_server.py
```

Then run the section-loop conductor in another terminal:

```bash
python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4
```

The conductor reads `public/live-control.json` before each 4-bar section, pre-generates 4 sections by default, then publishes HLS segments to `public/stream/index.m3u8`, writes `public/conductor-status.json`, and updates `public/sessions/<session-id>/current-stream.mp3`. During prebuffering, the page shows how many sections remain before live audio is ready.

To change the startup buffer:

```bash
python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4 --prebuffer-sections 8
```

By default, the growing current-session recording keeps only the latest hour. Older section MP3/WAV/TS files are trimmed as new sections arrive. Override the cap with:

```bash
python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4 --max-recording-seconds 1800
```

Use `--max-recording-seconds 0` only if you intentionally want an unbounded recording.

The conductor now routes every section through role-agent bundles. By default those agents are local heuristics, which keeps the demo reliable offline. To try OpenAI-compatible LLM role calls, set `OPENAI_API_KEY` and run:

```bash
OPENAI_API_KEY=... python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4 --agent-mode llm
```

Optional environment variables:

- `OPENAI_MODEL` defaults to `gpt-4o-mini`.
- `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`.
- `ADMIN_PASSWORD` or `ADMIN_SECRET` gates backstage admin controls. Generate with `openssl rand -base64 32` and keep it out of git.
- `SOUNDFONT_PATH` points to a local deploy-safe `.sf2` / `.sf3` file.
- `SOUNDFONT_PACK_ID` defaults to `general-midi`.

If an LLM call fails or returns invalid JSON, the conductor falls back to heuristic role bundles so the stream keeps playing.

## Improve sound rendering

By default, the renderer uses the internal synth plus FFmpeg polish: stereo role panning, EQ, compression, short echo/reverb, and limiting.

If you install FluidSynth and have a `.sf2`/`.sf3` soundfont, the same MIDI path can render through it:

```bash
SOUNDFONT_PATH=/path/to/soundfont.sf2 python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4
```

or:

```bash
python3 scripts/segment_conductor.py --session-id summit-demo --section-bars 4 --soundfont /path/to/soundfont.sf2
```

If FluidSynth or the soundfont is missing, the conductor automatically falls back to the internal synth plus effects.

Recommended soundfont policy:

- Default deploy-safe target: MuseScore General / FluidR3-style MIT-compatible General MIDI soundfonts.
- Conditional optional palette: GeneralUser GS, only with its license and sample-provenance caveat documented.
- Deferred orchestral source: VSCO2 Community Edition, only after a clean conversion and license file are added.
- Avoid unclear or restrictive packs such as SGM, Timbres of Heaven, commercial sample packs, or any pack without clear redistribution/service rights.

Music-side tools and libraries used by this repo include Python standard-library MIDI writing/parsing, FFmpeg, optional FluidSynth, hls.js in the browser, and OpenAI-compatible chat-completion calls for role-agent JSON when LLM mode is enabled.

For quick QA, stop after a few short sections:

```bash
python3 scripts/segment_conductor.py --session-id conductor-qa --section-bars 2 --max-sections 3
```

To verify that the playlist advances at live-ish wall-clock speed instead of transcode speed, run the generator in one terminal and then:

```bash
python3 scripts/qa_live_hls.py public/stream/index.m3u8 --startup-timeout-seconds 45 --sample-gap-seconds 6 --min-start-sequence 1
```

## Serve locally with controls

From the project root:

```bash
python3 scripts/control_server.py
```

Then open:

```text
http://127.0.0.1:8765/web/
```

The current UI lives at:

```text
http://127.0.0.1:8765/web/new/
```

`web/new/config.js` is the static frontend runtime config shim. For local development it uses same-origin defaults. For Vercel, generate or replace that file during the build/deploy step without changing `app.js`:

```js
window.AIPS_CONFIG = {
  backendBaseUrl: "https://radio-backend.example.com",
  mediaBaseUrl: "https://radio-media.example.com"
};
```

The frontend reads this before `app.js`, so the same static bundle can point at a Hetzner API/media host.

When the frontend and backend are on different origins, set `AIPS_ALLOWED_ORIGINS` on the Hetzner backend to the exact Vercel origin. The backend reflects only configured origins, sends `Access-Control-Allow-Credentials: true`, and the frontend uses credentialed fetches so anonymous voter cookies and HttpOnly admin sessions work cross-origin. Production cross-origin cookies also require `AIPS_SECURE_COOKIES=1` and `AIPS_COOKIE_SAMESITE=None`, which the Hetzner service example sets.

When nginx reverse-proxies `/api/` to the Python backend, it must pass the real listener address with `X-Real-IP` / `X-Forwarded-For`. The backend trusts forwarded client IPs only when the immediate peer is loopback or inside `AIPS_TRUSTED_PROXY_RANGES`; this keeps hashed-IP voting limits and aggregate unique-IP counts per listener instead of globally throttling every request as `127.0.0.1`.

Most non-Safari browsers need `hls.js`, which the page loads from a CDN. Safari can usually play HLS natively.

Press **Start live audio** on the page. Browsers block unprompted autoplay, so the live player will not make sound until you click the button. The current stream recording appears in its own section, and previous generated runs are listed below the live player as normal MP3 recordings.

If HLS is not supported by the browser or the live generator is not running, the live button falls back to the latest archived MP3.

The page also includes a **Live influence** control. Press **Apply to next section** to write `public/live-control.json`. The current generator reads that file when creating the next generated form and biases density, chord drift, texture, lead behavior, and bass stability from the prompt.

## Tweak personas

Open **Personas and prompts**, edit the text boxes, then press **Save personas**. This writes `public/personas.json` through `scripts/control_server.py`.

## Voting, suggestions, and admin controls

The control server exposes anonymous cookie-based voting (`/api/vote-round`, `/api/vote`), moderated style suggestions (`/api/suggestions`), admin login/logout (`/api/admin/login`, `/api/admin/logout`), vote-round curation (`/api/admin/vote-round`), suggestion promotion (`/api/admin/suggestions/promote`), backstage override (`/api/admin/override`), emergency archive fallback (`/api/admin/fallback`), admin health (`/api/admin/health`), and aggregate collapse metrics (`/api/admin/collapse`). Listener suggestions are stored for admin review and do not reach the conductor directly.

Votes are limited to one anonymous browser cookie per active round and additionally rate-limited by hashed IP. Role sub-votes are validated against the current round's curated role options and only change instrument/role preferences inside the winning global style envelope; they cannot directly override tempo, key, or meter.

Admin auth is password-based: set `ADMIN_PASSWORD` or `ADMIN_SECRET` in the deployment environment. The backend verifies it server-side and issues an HttpOnly session cookie with an 8-hour inactivity expiry. In production, run behind HTTPS and set `AIPS_SECURE_COOKIES=1`; the Hetzner examples default to this. Do not put the secret in frontend config, localStorage, committed files, or public logs.

Persistent radio state is private server state, not frontend content. Set `AIPS_STATE_DIR=/var/lib/aips/radio-state` (or another path outside the web root) for production. The local fallback is `.aips-state/radio-state`, and both the Python server and nginx example deny legacy `/public/radio-state/` and `/.aips-state/` URLs defensively.

## Hetzner + Vercel deployment shape

Vercel can serve the static frontend. Hetzner should run the stateful pieces: `scripts/control_server.py`, `scripts/segment_conductor.py`, FFmpeg/FluidSynth rendering, HLS/media serving, and archive storage. Example systemd units and nginx config live in `deploy/hetzner/`.

HLS segments should be served by nginx or an equivalent static file server from the conductor output directory. The Python backend owns state and control APIs.

The nginx example redirects HTTP to HTTPS, denies radio-state URLs, and the systemd units set secure-cookie mode plus `/var/lib/aips/radio-state` for private state. It also adds media CORS headers on `/public/stream/`, `/public/archive/`, `/public/recordings/`, and `/public/sessions/` so a Vercel page using `mediaBaseUrl` can load HLS playlists, TS segments, MP3s, and archive files from Hetzner. Replace the placeholder certificate paths, domain, and `https://your-vercel-app.vercel.app` origin before deploying.

## Archive model

Temporary HLS segments and WAV intermediates may rotate during live generation, but archived sessions are permanent research/art artifacts. Archive entries preserve MP3, MIDI, state, role bundles, prompts/style config, vote snapshots, timing metadata, render engine, time signature, selected instruments, and soundfont metadata when available.

## Concept and collapse

The project asks how many cycles it takes for an agentic system to capture a style in a prompt, how long before the style collapses, and how long a human can listen before the loop becomes aesthetically unstable. Collapse is defined behaviorally: people stop nudging, stop voting, repeat the same choice, or accept a strange middle ground as “close enough.”

## Open-source hygiene

Safe examples like `.env.example` may be committed. Do not commit real `.env` files, API keys, admin passwords/secrets, server credentials, generated cookies/session state, private radio-state data, private soundfonts, or soundfonts with unclear redistribution rights. If a soundfont is distributable, include its license. If not, document where to obtain it and how to install it on the server.

## Disclaimer

This experimental work is offered as parody, commentary, and research-oriented artistic expression. It is not affiliated with, sponsored by, endorsed by, or approved by any referenced artist, label, rights holder, or third party. All trademarks, copyrights, publicity rights, and related rights remain the property of their respective owners. No ownership, license, or transfer of rights is claimed or implied. The project is not intended to generate revenue, impersonate any artist, reproduce protected works, or violate applicable law.

## Current limitations

LLM mode and FluidSynth are optional and fall back to heuristic role bundles and the internal synth when unavailable. The server remains a pragmatic single-station architecture, not a multi-room radio platform.
