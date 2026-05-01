# AI Ensemble Live Stream Design

Date: 2026-04-25
Status: Accepted concept; Day 1 dummy stream implemented separately
Working directory: `/Users/keecraw/SAA-day/aips`

## Goal

Build a four-to-five-role AI music ensemble that plays a continuous lo-fi / ambient / jam-band stream with controlled “AI psychosis” moments. Audience members can listen from a website, while one trusted contributor can submit a feeling, mood, or song-like prompt that affects the next musical section after a short live delay.

The system should feel like a small ensemble: percussion, bass, piano / harmony, horn / lead, and optionally texture / pads. The agents do not need to produce conservatory-grade jazz. They need to play coherent, listenable music, visibly react to each other, and provide a strong demo narrative.

## Recommendation Summary

Use Approach A: a symbolic MIDI multi-agent system with a custom coordinator / conductor. Do not use LatentMAS for v1. Do not train or fine-tune models for v1. Use API-accessible LLMs to generate compact symbolic phrases, render those phrases to audio with high-quality samples, then stream the rendered audio through standard live-audio infrastructure.

This is the best fit for a four-day build and a budget under $200 because the hard part is not raw sound synthesis. The hard part is reliable coordination: tempo, key, chord grid, role balance, turn-taking, fallback behavior, prompt updates, and demo stability. Symbolic MIDI makes those concerns inspectable and controllable.

## LatentMAS Decision

LatentMAS should be treated as a post-build v2 investigation, not a v1 dependency. Based on the current goal, it is unlikely to lower latency in the path that matters. The latency bottlenecks are model inference, chunk scheduling, rendering, buffering, and live-stream delivery. A multi-agent framework can organize messages, but it does not make an LLM produce music faster or make audio streaming lower-latency.

It may make coordination conceptually cleaner if it offers shared latent-state coordination, agent memory, or structured multi-agent negotiation. But for this demo, the coordination problem is small and timing-sensitive: four or five roles, a bar clock, a shared score state, and deadline-or-skip semantics. A custom Python coordinator will be faster to build, easier to debug, and easier to constrain.

LatentMAS can be revisited after v1 if the demo works and the next goal is research novelty rather than shipping reliability.

## Architecture

The system has five bounded units.

1. **Coordinator / Conductor**: owns the canonical musical state: tempo, key, chord grid, bar number, form section, active soloist, psychosis level, current prompt, deadline windows, and reset motif. It schedules each agent and decides whether to accept, simplify, or skip late output.

2. **Role Agents**: each role receives a compact view of the last few bars and emits the next phrase in a strict symbolic format. Roles are percussion, bass, harmony / piano, lead / horn, and optional texture. Agents are not allowed to change global state directly; they propose musical material and metadata.

3. **Symbolic Merger**: validates agent output, clips impossible values, quantizes timing, applies velocity / density constraints, and merges tracks into one MIDI segment.

4. **Renderer / Streamer**: renders MIDI to audio using high-quality soundfonts or sample libraries, stitches segments into a continuous stream, keeps a 20-30 second buffer, and serves the live feed to browsers.

5. **Website / Visual Layer**: provides a listen page, one contributor prompt form, static / playing animations for instrumentalists, agent status indicators, and a rolling visualization of recent musical activity.

## Timing and Latency Model

The system should generate ahead of the listener. “Live” means the browser is playing a delayed stream, not that listeners hear the exact instant the models produce notes. The coordinator should maintain a rolling buffer of roughly 20-30 seconds.

Each generation tick should target a small musical unit, likely 2 or 4 bars. Agents run with deadlines. If an agent misses the deadline, the coordinator uses one of three fallbacks: repeat / vary its previous phrase, play a safe reset motif, or mute that role for the segment.

This avoids a latency cascade. No agent should block the entire band indefinitely.

## Reset and Re-Alignment

The ensemble needs a safe musical place to recover. Use a reset motif rather than “everyone panic and improvise.” Good options:

- A short leitmotif that all agents know.
- A tonic pedal or suspended chord for harmony and bass.
- A simple percussion groove that re-establishes tempo.
- A scalar pickup into the next section.

The reset should be triggered when outputs are late, invalid, harmonically chaotic, or too dense. It can also be used theatrically during “AI psychosis” moments: the band drifts, then the conductor pulls everyone back with the motif.

## Who Controls Tempo, Key, and Chords

The user proposal is musically intuitive but needs guardrails. Percussion can suggest tempo feel, the soloist can suggest key color, and the pianist can suggest harmonic movement, but the conductor must own the canonical state.

Recommended rule:

- **Conductor owns truth**: tempo, key, chord grid, section, and soloist.
- **Percussion influences groove**: swing, density, fills, half-time / double-time feel, but not raw BPM except at section boundaries.
- **Piano / harmony agent proposes chord substitutions**: accepted only at phrase boundaries and only if they fit the current key / mode policy.
- **Soloist proposes emotional / modal color**: brightness, tension, register, motif, and call-and-response, but cannot unilaterally reset key.
- **Bass stabilizes**: root motion, pedal tones, walking patterns, and recovery behavior.

This keeps the band expressive without letting four agents fight over the steering wheel.

## Symbolic Feedback Loop

### Layperson explanation

Instead of having the AIs listen to raw sound like a person hears music, we show them a simplified written-down version of what just happened: who played what notes, when, how loud, and over which chords. They use that as context to decide what to play next.

### Musician explanation

The feedback loop is like handing every player a mini lead sheet plus a transcript of the last few bars: chord symbols, rhythmic hits, recent motifs, density, and who is soloing. The bass player sees the drummer’s groove and piano voicings; the horn sees the chord grid and recent comping; the drummer sees whether the soloist is building or laying back.

### AI researcher explanation

It is a compressed state representation for closed-loop generation. The environment state is not raw waveform audio; it is symbolic event history plus global control variables. Each agent conditions on a bounded context window of structured tokens and emits an action sequence. The coordinator validates actions, updates the shared state, and rolls the window forward. This makes credit assignment, constraint enforcement, pruning, and observability much easier than audio-in/audio-out generation.

## “Stop Soloing” as Prompt Rule, Not Reward Signal

For v1, do not train a reward model and do not use reinforcement learning. “Stop soloing” should be encoded as a protocol rule inside the agent prompt and conductor policy.

The AI version: reinforcement learning would require defining a reward, collecting many trajectories, evaluating musical quality, and updating model weights or a policy. That is expensive, slow, and unstable for an aesthetic objective.

The engineering version: the conductor tracks solo length and intensity. If the horn has soloed for 8 bars, the next prompt tells it to resolve its phrase and yield. The conductor then lowers its allowed note density and raises another role’s foreground permission. If the agent ignores this, the validator clips or mutes it.

This gets the desired behavior deterministically without training.

## Model Choice: Claude Sonnet vs Open-Weight Models

Claude Sonnet or a comparable frontier API model is recommended for v1 because it follows complex musical instructions, role constraints, formatting constraints, and state-machine rules reliably. For this project, reliability is more valuable than owning the weights.

What API models gain:

- Better instruction-following for role behavior and strict output format.
- No GPU setup or serving overhead.
- Faster iteration on prompts.
- Better reasoning about conductor rules, “yield the solo,” and mood shifts.

What open-weight models gain:

- Lower marginal cost at scale if already hosted efficiently.
- More control over system behavior.
- Potentially lower latency with a local optimized server.
- Easier future fine-tuning on a custom symbolic music corpus.

What open-weight models lose for v1:

- More setup time.
- More prompt-format failures.
- More debugging around serving, quantization, throughput, and context handling.
- Higher risk within a four-day deadline.

Recommended v1 model strategy: use one stronger model for the conductor / critic role and cheaper, faster models for individual performers where possible. If cost becomes a problem, downgrade texture, percussion, or bass first; keep the conductor reliable.

## Soundfonts and Audio Quality

A soundfont is a packaged library of instrument samples that a MIDI synthesizer uses to turn notes into audio. MIDI says “play this note at this time with this velocity.” The soundfont determines whether that note sounds like a toy keyboard, a warm upright bass, a brush kit, or a convincing horn patch.

The fastest way to make this demo sound better is not model training. It is better rendering:

- Use a strong General MIDI base soundfont, then override key instruments with better samples.
- Favor Rhodes / electric piano over acoustic piano, because it hides MIDI stiffness better.
- Use upright or electric bass with compression.
- Use brush drums, rim clicks, shakers, and soft kits instead of aggressive acoustic drums.
- Use sax / horn sparingly; fake horns expose bad samples quickly.
- Add reverb, tape saturation, light compression, EQ, and limiter after rendering.
- Consider making the lead instrument a synth, flute-like pad, or processed sax texture instead of a naked realistic sax.

The target aesthetic should be “late-night generative lounge / ambient jam,” not “real Blue Note quartet.”

## Descriptive Style Palette

Avoid prompts that ask the model to imitate living or named artists directly. Use descriptive style tags inspired by the references instead.

Suggested palette:

- **Spiritual modal sax energy**: searching, scalar, long arcs, rising tension, occasional sheets of notes, resolves into simple motifs.
- **Cool muted trumpet restraint**: spacious, lyrical, behind the beat, fewer notes, strong use of silence.
- **Odd-meter lounge pulse**: asymmetric accents, lightly swinging, playful but controlled.
- **West Coast cosmic jazz**: big modal harmony, warm ensemble swells, celebratory brass-like phrases.
- **Indie-folk haze**: intimate, grainy, soft harmonic loops, fragile melodic fragments.
- **Electronic soul minimalism**: sparse chords, negative space, sub-bass warmth, clipped rhythmic cells.
- **Circular-breathing reed texture**: pulsing arpeggios, droning overtones, mechanical repetition that mutates slowly.
- **Art-funk nocturne**: syncopated bass, glassy keys, dry drums, stylish restraint.
- **Southern rock-soul grit**: raspy lead gestures, blues bends, earthy call-and-response.
- **Psychosis drift**: motifs repeat too often, harmonic gravity weakens, rhythms phase slightly, then the reset motif restores coherence.

These tags can be combined with direct musical controls: tempo range, density, register, brightness, swing amount, dissonance level, and solo intensity.

## Website and Visual Design

The website is a listening surface, not a full multi-user app. It should include:

- A live audio player that joins the current stream.
- One contributor prompt form, gated by a simple secret or admin route.
- Four or five instrumentalist cards with static / playing animations.
- Status per role: listening, composing, playing, skipped, reset.
- A small “currently influenced by” prompt display.
- Optional rolling piano-roll or simplified activity bars.

Only one contributor can affect the stream during the demo. All other visitors just hear the current live stream.

## Streaming and Recording

Use a standard delayed live-stream pattern. The generator produces chunks ahead of playback. The stream server exposes the current rolling audio feed. Browsers join the stream with a delay.

Preferred v1 path: render MIDI segments to WAV, encode with FFmpeg, and stream through Icecast or HLS. HLS is browser-friendly and works well with a 20-30 second delay. Icecast is simpler for internet-radio-style MP3 streaming. The implementation plan should choose one after testing local setup speed.

Continuously record the output. Keep a pre-recorded fallback reel ready for the summit. The fallback is not a compromise; it is demo insurance.

## Data and Storage

Store enough data to debug and replay:

- Prompt submissions.
- Coordinator state per segment.
- Agent input and output per segment.
- Validated MIDI segments.
- Rendered audio chunks.
- Stream health logs.

For v1, SQLite or simple files are enough. A full database can wait unless deployment requires it.

## Context Pruning

Do not pass raw full history to every agent. Maintain a compact context:

- Global: key, tempo, chord grid, section, soloist, psychosis level.
- Recent: last 4-8 bars of symbolic events.
- Summary: motifs, density, tension, and role activity from the previous section.
- Hard constraints: max notes, allowed register, required yield / support behavior.

This avoids runaway token costs and keeps agent outputs aligned.

## Moderation and Safety

Because only one contributor controls prompts during the demo, moderation can be simple. Still, prompt input should be filtered for hateful, sexual, or unsafe content, and the displayed prompt should be sanitized. Public visitors should not be able to submit arbitrary prompts.

## Failure Modes and Mitigations

- **Latency cascade**: deadline-or-skip, repeated phrase fallback, reset motif.
- **Bad musical output**: constrain format, use lo-fi aesthetic, use safe groove templates.
- **Harmonic drift**: conductor-owned key and chord grid.
- **Excessive soloing**: conductor tracks solo length; prompt rule plus validator enforcement.
- **Toy MIDI sound**: better soundfonts, effects chain, Rhodes / pads / soft drums.
- **Context explosion**: symbolic pruning and summaries.
- **Model format errors**: strict schema, retries, fallback phrase library.
- **Stream outage**: pre-recorded fallback and local playback option.
- **Prompt abuse**: one contributor only, input filtering.
- **Audience boredom**: visual agents, status indicators, prompt-reactive moments, psychosis drift / recovery narrative.

## Four-Day Build Scope

### Day 1: End-to-end dummy stream

Create dummy MIDI loops for each role, render to audio, stream to browser, and record output. This proves the riskiest infrastructure path before adding intelligence.

### Day 2: Coordinator and role agents

Implement the bar-clock coordinator, shared state, symbolic format, agent prompts, validator, fallback phrases, and fixed-form generation.

### Day 3: Prompt reactivity and visuals

Add the contributor prompt route, mood-to-state mapping, role animations, status displays, psychosis dial, and reset motif behavior.

### Day 4: Polish and rehearsal

Tune soundfonts, mix, effects, fallback reel, deploy, monitor cost, dry-run the summit demo, and prepare a one-click emergency fallback.

## Explicit Non-Goals for v1

- No fine-tuning.
- No reinforcement learning.
- No LatentMAS dependency.
- No fully audio-native multi-agent model.
- No public multi-user prompt queue.
- No claim that the system is producing expert jazz.

## Acceptance Criteria

The v1 demo is successful if:

1. A listener can open the website and hear a continuous generated stream.
2. The stream is generated from four or more symbolic role agents.
3. A trusted contributor can submit a prompt that changes the music within the next 1-2 sections.
4. The visual interface shows role activity and playing / listening states.
5. The system can recover from late or invalid agent output without stopping playback.
6. A fallback recording can be played if the live system fails.
7. The total build and demo operation remains under the $200 budget target.

## Implementation Addendum: Day 1 Decisions

### 1. Streaming path

Use **HLS** as the v1 stream target. HLS fits the intentional 20-30 second delay, can be generated from local audio files with FFmpeg, and can be served as static files from `public/stream/`. Safari can play HLS natively; other browsers can use `hls.js` on the listener page.

Icecast remains a backup option if the implementation later needs internet-radio-style MP3 streaming, but it is not the Day 1 default.

### 2. Symbolic contracts

There are three related contracts. Day 1 implements the internal event and website state contracts. Day 2 role agents will emit role bundles that the conductor flattens into the same internal event contract.

#### 2.1 Role-agent output bundle

Role agents will emit one bundle per role per generated segment:

```json
{
  "segment_id": 1,
  "role": "bass",
  "status": "playing",
  "events": [
    { "bar": 1, "beat": 1.0, "duration_beats": 1.0, "pitch": 48, "velocity": 76 }
  ],
  "metadata": {
    "density": 0.4,
    "solo_intensity": 0.1,
    "supports_soloist": true
  }
}
```

#### 2.2 Internal event contract

The conductor/merger and Day 1 generator use a flat list of events:

```json
{
  "role": "bass",
  "bar": 1,
  "beat": 1.0,
  "duration_beats": 1.0,
  "pitch": 48,
  "velocity": 76
}
```

The renderer consumes only this internal event contract. The Day 2 conductor will transform each role-agent output bundle into these flat events after validation.

#### 2.3 Website state contract

The listener page reads `state.json`:

```json
{
  "tempo_bpm": 92,
  "key": "A minor",
  "bars": 16,
  "roles": ["bass", "lead", "percussion", "piano", "texture"],
  "stream": "index.m3u8",
  "status": { "bass": "playing" },
  "events": []
}
```

Day 1 writes this website state contract directly. This is intentional: the page needs the stream URL, role statuses, and a debug-visible event list, while the role-agent bundle contract is reserved for Day 2.

### 3. Coordinator state machine

The coordinator starts with a small explicit state machine:

- `BOOT`: initialize tempo, key, chord grid, role list, and output directories.
- `PREFILL`: generate enough segments to create a delayed stream buffer.
- `GENERATE`: ask each role for the next segment before its deadline.
- `VALIDATE`: quantize and reject impossible or late events.
- `RENDER`: merge symbolic events into MIDI/audio artifacts.
- `PUBLISH`: expose updated stream files and role status to the website.
- `RESET`: use a known motif/pedal/groove if generation fails or drift is too high.

The conductor owns canonical tempo, key, chord grid, section, active soloist, and reset policy. Roles can suggest changes, but the conductor commits them only at segment boundaries.

### 4. Role prompt contract

The later LLM role prompts must produce only schema-compatible symbolic output. They receive the current conductor state, the last 4-8 bars of compact event history, their role constraints, and a deadline. If output is invalid or late, the conductor falls back instead of blocking playback.

Day 1 does not call LLMs. It builds the streamable dummy band that proves the rendering and browser-listening path.

#### 4.1 Conductor prompt template

```text
You are the conductor for a symbolic AI ensemble. Given the current state, choose the next segment plan.

Current state:
{conductor_state_json}

Recent event summary:
{recent_events_json}

Return only JSON with this shape:
{
  "segment_id": 1,
  "tempo_bpm": 92,
  "key": "A minor",
  "chord_grid": [{ "bar": 1, "symbol": "Am9" }],
  "active_soloist": "lead",
  "psychosis_level": 0.2,
  "role_directives": {
    "percussion": "keep soft brushed pulse",
    "bass": "stabilize roots and fifths",
    "piano": "sparse Rhodes voicings",
    "lead": "short lyrical motif then leave space",
    "texture": "low pad, no foreground motion"
  },
  "fallback_policy": "repeat_previous_then_reset_motif"
}
```

#### 4.2 Shared role prompt template

```text
You are the {role} player in a symbolic AI ensemble. You must write the next segment only for your role.

Conductor state:
{conductor_state_json}

Recent events:
{recent_events_json}

Role directive:
{role_directive}

Hard constraints:
- Return only valid JSON.
- Use MIDI pitch numbers.
- Use bar and beat positions relative to this segment.
- Keep all durations positive.
- If uncertain or under time pressure, emit a sparse safe support pattern instead of soloing.
- Do not change tempo, key, or chord grid.

Return only this JSON shape:
{
  "segment_id": 1,
  "role": "{role}",
  "status": "playing",
  "events": [
    { "bar": 1, "beat": 1.0, "duration_beats": 1.0, "pitch": 48, "velocity": 76 }
  ],
  "metadata": {
    "density": 0.4,
    "solo_intensity": 0.1,
    "supports_soloist": true
  }
}
```

#### 4.3 Role-specific constraints

- **Percussion**: prioritize tempo feel, light swing, kick/snare/hat patterns, and fills only near segment endings. Never set BPM directly.
- **Bass**: prioritize root motion, fifths, pedal tones, and recovery. Avoid dense upper-register lines unless explicitly soloing.
- **Piano**: provide sparse chord voicings and substitutions only inside the conductor's chord grid. Prefer Rhodes-like restraint.
- **Lead**: play short motifs, leave space, and yield when `solo_intensity` has been high for too long.
- **Texture**: provide pads, drones, or simple high-register color. Avoid foreground melodic competition.

### 5. Fallback behavior

Fallbacks are ordered from least disruptive to most disruptive:

1. Repeat and slightly vary the role's previous phrase.
2. Play the role's safe support pattern.
3. Trigger the shared reset motif.
4. Mute the role for one segment.

The stream should continue even if an individual role fails.
