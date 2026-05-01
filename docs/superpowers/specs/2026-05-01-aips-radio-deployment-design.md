# AIPS Radio Deployment Design

Date: 2026-05-01
Status: Draft approved in brainstorming; ready for user review
Working directory: `/Users/keecraw/SAA-day/aips`

## Goal

Turn the current local AI ensemble demo into a public single-station radio experience for the AIPS Summit. The system should host one continuous generated stream, let listeners vote on what the next two minutes should emulate, preserve previous sessions as a public archive, and explain the project as a Resoworks meditation on the Chinese Room and LLM-style imitation.

The design is split into three phases so the deployment, music-quality work, and conceptual/research framing can each be built and tested independently.

## Phase 1: Public Radio, Voting, Admin, Archive, and Deployment

### Architecture

Use **Vercel for the public frontend** and **Hetzner for the stateful backend**.

Vercel serves the public interface: live player, voting panel, suggestion form, About page, and archive browser. Hetzner runs the Python API, the always-on conductor process, FFmpeg/FluidSynth rendering, HLS publishing, admin auth, vote state, suggestion moderation state, and persistent archive storage.

HLS segments are served from Hetzner through a static file server, preferably nginx, fronting the conductor output directory. The Python backend owns state and control APIs; nginx owns efficient media delivery.

This matches the current code better than a pure Vercel deployment. The existing conductor is a long-running process that writes HLS segments and media files to disk. Vercel serverless functions are not the right place for continuous FFmpeg rendering, local-file playlist mutation, or permanent archive storage.

### Live Stream Flow

There is one global station. The conductor generates one approximately two-minute section at a time. Each section applies the latest approved style state, renders MIDI to audio, publishes live HLS, and stores permanent artifacts when the section/session completes.

The frontend plays the Hetzner-hosted HLS stream. If the live conductor or HLS playlist is unavailable, the player falls back to the latest archived MP3 loop so the public experience degrades into archive radio rather than silence. The frontend treats a playlist 404, playlist parse failure, or load timeout as stream unavailable. Before any archive exists, the fallback state shows “stream initializing” rather than attempting MP3 playback.

### Voting Model

Listeners vote anonymously through a cookie-based identity. There is no listener sign-up in Phase 1. The backend also applies IP and rate limits to reduce vote stuffing.

Voting uses a fixed-menu model. Admins curate 2-4 candidate options for each round. The public vote selects the global style envelope for the next generated section. The global winner sets coherence-critical values such as tempo, key, form, density, and overall prompt direction.

Role sub-votes are in Phase 1 scope. They may influence bass, percussion, piano/harmony, lead, and texture inside the winning global envelope. This avoids the incoherence of letting each role independently set tempo/key while still allowing listeners to shape hybrid configurations.

The UI must show when a vote will become audible. The conductor may be buffered ahead, so the vote result can apply to a future section rather than the section currently playing.

### Suggestions and Abuse Controls

Listeners may submit suggestions, but listener free text never reaches the conductor directly. Suggestions are stored in a pending queue and require admin approval before they can become future fixed-menu choices.

Suggestion moderation should reject or quarantine:

- Prompt injection or operational instructions.
- Attempts to reveal secrets, system prompts, admin state, or server details.
- Direct requests for copyrighted lyrics or direct replication of protected works.
- Hateful, sexual, violent, harassing, or otherwise unsafe content.
- Attempts to impersonate artists, rights holders, organizers, or administrators.

The safest default behavior is refusal: if a suggestion is ambiguous or risky, it should not enter the public menu without admin review.

### Admin Auth and Controls

Admin access is protected by a password set through Hetzner backend environment variables. Generate the secret with a command such as:

```bash
openssl rand -base64 32
```

Store it as an environment variable such as `ADMIN_PASSWORD` or `ADMIN_SECRET`. The admin login form submits the password to the backend, the backend verifies it server-side, and the backend issues an HttpOnly admin session cookie. The password must never be placed in frontend config, localStorage, committed files, or public logs.

Admin sessions expire after 8 hours of inactivity. A logout endpoint invalidates the session cookie server-side.

Admin controls include:

- Curate fixed-menu voting options.
- Approve or reject listener suggestions.
- Set or override the next style backstage.
- Toggle emergency fallback.
- View conductor, LLM, render, archive, and vote health.

Admin override is backstage by default. Public listeners see round options, results, and playback state, not staff intervention. Emergency/offline states may be public when needed.

### Permanent Archive

The system should not trim old generated sessions out of existence. Temporary HLS segments and WAV files may rotate during live generation, but completed session artifacts should be preserved.

The public archive stores:

- Final MP3 recording.
- MIDI artifact.
- Applied prompts and style config.
- Role bundles.
- Vote snapshot.
- Timing metadata.
- Render engine and soundfont metadata when available.

A role bundle is the per-role generation record for a section: role name, prompt/directive text, selected MIDI program or instrument-pool entry, generated note events, density/solo/support metadata, and source (`heuristic`, `llm`, or fallback).

Archive pages are public. The archive is part of the artwork/research record, not just an operational backup.

### Legal Disclaimer

The About page and relevant archive/style surfaces should include formal disclaimer language covering parody/commentary, non-affiliation, no endorsement, no revenue intent, no transfer of rights, and all rights reserved to respective copyright holders.

The disclaimer should be legalese-style, while the explanatory page around it can remain readable and art-facing. The language should make clear that the project is an experimental commentary/parody work and is not intended to generate revenue, impersonate artists, infringe rights, or violate applicable law.

## Phase 2: Musical Variety, Instrument Groups, and MIDI Packs

### Scope

Phase 2 improves musical variety while keeping the current five-role model:

- Percussion.
- Bass.
- Piano/harmony.
- Lead.
- Texture.

Do not expand the number of roles first. The highest-value improvement is richer behavior inside the existing roles: more rhythm cells, bass movement types, voicing templates, lead contours, texture behaviors, density ranges, MIDI programs, and style-specific constraints.

### Style and Role Voting Rules

The winning global style remains the coherence envelope. It owns tempo, key, broad form, density, and time signature. Role sub-votes can bias individual instruments inside that envelope but do not directly override tempo/key.

Clamp minimum tempo to **60 BPM**.

Advanced musical controls such as odd meters, harmonic substitutions, mode changes, and unusual forms are admin/preset-authored only in Phase 2. Public voting remains legible and curated.

### Time Signatures and Musical Terms

4/4 remains the default. Add support conservatively:

- 3/4 and 6/8 are safe early presets.
- 5/4 and 7/8 are admin-only experiments after QA.
- More complex terms should be represented as preset metadata and conductor constraints, not raw listener text.

### Instrument Groups Per Role

Each role becomes an **instrument group**, not a single MIDI program. The conductor still thinks in five roles, but each role can choose from a curated pool of instruments.

Example pools:

- **Percussion**: standard kit, room kit, power kit, jazz kit, and admin-sourced electronic/break kits only when they satisfy the soundfont licensing policy below.
- **Bass**: upright, finger electric, picked electric, fretless, slap, synth bass, sub bass.
- **Piano/harmony**: acoustic piano, Rhodes/electric piano, organ, nylon guitar, steel guitar, bells, mallets, string comping.
- **Lead**: alto/tenor sax, flute, violin, trumpet, square lead, saw lead, choir/voice-like lead.
- **Texture**: warm pad, polysynth pad, choir pad, halo/sweep pad, strings, glass/crystal, atmosphere/noise-like layers.

The current code supports one MIDI program per role and one global soundfont. Phase 2 should move toward config-driven instrument pools and explicit role/channel assignment. Where possible, the renderer should choose instruments from a role pool algorithmically or from preset metadata, then store the chosen instrument metadata in the archive.

### Soundfont and MIDI Pack Policy

Prioritize legally deployable FluidSynth-compatible packs:

1. **MuseScore General / FluidR3-style MIT soundfonts** as the primary General MIDI workhorse.
2. **GeneralUser GS** as an optional secondary tonal palette only after documenting its custom permissive license and sample-provenance caveat in the README. It is acceptable as a conditional candidate, not the default pack.
3. **VSCO2 Community Edition** as a deferred CC0 orchestral texture source. It should not be required for Phase 2 unless a clean conversion/packaging process and license file are added explicitly.

Avoid packs with unclear or restrictive redistribution/service rights, including SGM, Timbres of Heaven, commercial sample packs, and any pack without clear license terms.

Soundfonts and license files should live on Hetzner. Do not download soundfonts at runtime. Do not commit private or legally ambiguous packs to the public repo. If a pack is used, the README and archive metadata should identify the pack, source URL, license, and any caveats.

## Phase 3: About Page, Chinese Room Framing, and Collapse

### Conceptual Framing

The About page explains that this is a Resoworks project created for the AIPS Summit. It is a meditation on the Chinese Room and on LLM systems as procedural imitations of understanding.

The public framing should note that the original experiment has been adapted into an ongoing radio station where listeners vote on what style the next two minutes should emulate.

### Experiment Questions

The project asks:

1. How many cycles does it take for an agentic system to capture a style in a prompt?
2. How long before the style collapses?
3. How long can a human listen before the experience becomes psychologically or aesthetically unstable?

### Collapse Definition

Collapse is artistically defined through human behavior, not a strict mathematical score. Collapse occurs when people stop nudging the model.

This could mean:

- The system reached a convincing copy of the desired style.
- The system settled into a strange middle ground.
- No one is using it anymore.
- Listeners have entered a shared delusional state and believe the system has reached the target.

Phase 3 should log behavior that supports this interpretation: vote frequency, repeated choices, abstentions, suggestion rate, inactivity periods, and convergence around one option.

Music metrics may be collected later, but they are evidence, not the canonical definition.

### About Page Tone

Use a hybrid tone. Start with a credible institutional/art-label explanation so the project is understandable at the summit. Then add a stranger experiment-log layer that reflects the obsessive, recursive, “how long before this breaks us?” premise.

## README and Open-Source Hygiene

The repo should include an open-source-ready `README.md` that explains:

- What the project is.
- How the public radio works.
- The Vercel + Hetzner deployment model.
- How the conductor process works.
- How voting, suggestions, admin override, fallback, and archive storage work.
- The Chinese Room/AIPS/Resoworks framing.
- The MIDI roles and instrument-group model.
- Soundfonts, MIDI packs, libraries, and music-side tools used or recommended.
- License notes and attribution requirements for soundfonts and third-party assets.

Secrets and sensitive operational files must not be committed. Commit only safe examples such as `.env.example`. Never commit:

- `.env` files.
- API keys.
- Admin password/secret.
- Server credentials.
- Private soundfonts or packs with unclear redistribution rights.
- Generated session cookies, auth state, or moderation/admin data.

If soundfonts are distributable, include their licenses. If not, document where to obtain them and how to install them on Hetzner.

## Acceptance Criteria

The design is accepted when:

- Phase 1 clearly specifies the Vercel frontend and Hetzner backend split.
- Phase 1 includes anonymous cookie voting, fixed-menu voting, moderated suggestions, admin password auth with HttpOnly session cookies, permanent archives, fallback playback, and legal disclaimer requirements.
- Phase 1 names nginx or an equivalent static file server as the Hetzner HLS serving layer.
- Phase 1 defines fallback behavior for HLS failure and first-run/no-archive states.
- Phase 1 defines admin session expiry and logout behavior.
- Phase 1 requires the voting UI to display when the current round's winning style becomes audible, accounting for conductor buffering.
- Phase 1 requires the About page to include a legal disclaimer covering parody/commentary, non-affiliation, no endorsement, no revenue intent, no transfer of rights, and all rights reserved language.
- Phase 2 keeps the current five-role model while adding richer musical vocabulary, tempo minimum, admin-only advanced musical controls, and instrument groups.
- Phase 2 names the default deploy-safe soundfont candidate, marks conditional candidates as conditional, and explicitly avoids unclear/restrictive packs.
- Phase 3 explains the Chinese Room framing, listener voting adaptation, behavior-defined collapse, and hybrid About page tone.
- Phase 3 requires an About page containing the three experiment questions and the behavior-defined collapse framing.
- Phase 3 requires behavior logging for vote frequency, repeated choices, suggestion rate, inactivity periods, and convergence around one option.
- README/open-source hygiene requirements are captured.

## Non-Goals

- Multi-room radio.
- Listener accounts in Phase 1.
- Direct listener free text reaching the conductor.
- Pure Vercel long-running audio generation.
- Commercial sample packs or unclear-license soundfonts.
- Expanding beyond the five current roles before improving their vocabulary.
