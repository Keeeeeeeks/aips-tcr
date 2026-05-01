# Phase 2 Implementation Plan: Music Variety and Instrument Groups

Date: 2026-05-01
Status: Planned
Design source: `docs/superpowers/specs/2026-05-01-aips-radio-deployment-design.md`

## Goal

Improve the musical variety of the existing five-role ensemble without expanding the role count. Add richer style-specific vocabulary, conservative time-signature support, minimum tempo enforcement, config-driven instrument groups, and legally curated FluidSynth-compatible soundfont handling.

## Acceptance Criteria

Phase 2 is complete when:

1. The system still uses the five existing roles: percussion, bass, piano/harmony, lead, and texture.
2. Each role has a richer pattern vocabulary with style-specific rhythm, pitch, density, and behavior constraints.
3. Tempo is clamped to a minimum of 60 BPM.
4. Public voting cannot directly set tempo/key/time signature outside the global style envelope.
5. 4/4 remains default; 3/4 and 6/8 are supported as safe presets; 5/4 and 7/8 remain admin-authored/QA-only.
6. Each role can select from a curated instrument pool rather than a single hard-coded MIDI program.
7. MuseScore General / FluidR3-style MIT soundfonts are the default deploy-safe pack option.
8. GeneralUser GS is documented only as conditional and not required.
9. VSCO2 Community Edition remains deferred unless a clean conversion and license file are explicitly added.
10. Archive metadata records selected instruments, soundfont pack, source URL/license identifier, and caveats.
11. README lists the MIDI packs, soundfonts, libraries, and music tools used or recommended.

## Implementation Steps

### 1. Add music configuration schema

- Create a config file for style definitions, role behavior, and instrument pools.
- Keep current `preset-modes.json` compatible or migrate it with a script.
- Define per-style:
  - tempo range,
  - key/mode policy,
  - time signature,
  - density range,
  - allowed role behaviors,
  - instrument-pool preferences.

### 2. Enforce tempo and style-envelope rules

- Update live-control/preset parsing so effective tempo is never below 60 BPM.
- Ensure role sub-votes cannot override tempo/key/time signature directly.
- Make advanced musical terms admin/preset-authored only.

### 3. Expand role pattern vocabulary

- Percussion: add style-specific groove cells, fills, rests, half-time/double-time feel, break-like patterns, and meter-aware accents.
- Bass: add root/fifth support, walking motion, pedal tones, octave jumps, chromatic approaches, syncopated funk, sub pulses, and sparse long-tone modes.
- Piano/harmony: add voicing templates, comping rhythms, suspended colors, extended chords, stabs, arpeggios, and sparse pads.
- Lead: add motif shapes, call-and-response, hooks, angular leaps, chromatic bites, lyric fragments, and silence rules.
- Texture: add drones, pads, shimmer, choir-like layers, noise beds, glass/crystal gestures, and density-aware masking constraints.

### 4. Add conservative time-signature support

- Introduce a section meter object instead of assuming 4 beats per bar everywhere.
- Update event validation to clamp beats against the active meter.
- Update MIDI writing and section duration calculation to honor meter.
- Add QA fixtures for 4/4, 3/4, and 6/8.
- Keep 5/4 and 7/8 admin-only until they pass manual listening QA.

### 5. Add role instrument pools

- Replace one-program-per-role assumptions with named instrument choices.
- Keep a compatibility path where a role can still resolve to a single General MIDI program.
- Define starter pools:
  - percussion: standard, room, power, jazz, licensed/admin-sourced electronic or break kits,
  - bass: upright, finger electric, picked, fretless, slap, synth, sub,
  - harmony: acoustic piano, electric piano/Rhodes, organ, guitars, bells, mallets, strings,
  - lead: sax, flute, violin, trumpet, square lead, saw lead, voice/choir-like lead,
  - texture: warm pad, polysynth, choir pad, halo/sweep, strings, glass/crystal, atmosphere.
- Record selected instrument labels and program/bank references in role bundles.

### 6. Improve FluidSynth rendering path

- Use MuseScore General / FluidR3-style MIT soundfont as default deploy-safe target.
- Add config for soundfont path, pack id, source URL, and license id.
- If adding multi-soundfont support, explicitly select per-channel program/bank instead of relying on FluidSynth stack order.
- Do not require GeneralUser GS or VSCO2 for Phase 2 completion.

### 7. Update LLM generation schema and validation

- Extend generation params to express instrument-pool preferences without allowing arbitrary unsafe pack names.
- Validate any LLM-suggested program/instrument against configured pools.
- Ensure invalid instrument suggestions fall back to the style/default pool.

### 8. Update archive and README

- Archive selected instruments, role pool ids, soundfont pack, source URL/license, and caveats.
- Update README with:
  - current music pipeline,
  - FluidSynth/FFmpeg usage,
  - General MIDI role mapping,
  - soundfont policy,
  - packs used/recommended/avoided,
  - installation instructions for Hetzner.

## Unit and Integration Tests

- Tempo parsing clamps values below 60 BPM.
- Public vote data cannot set direct tempo/key/time-signature overrides outside the global style envelope.
- 4/4, 3/4, and 6/8 fixtures produce valid event timing.
- 5/4 and 7/8 are rejected or admin-only according to config.
- Every role resolves to a valid configured instrument.
- Invalid instrument ids fall back to safe defaults.
- MIDI writer emits valid program/channel assignments for selected instruments.
- Archive metadata includes selected instrument and soundfont/license fields.
- README references only allowed/default soundfont packs as deploy-safe and marks conditional packs as conditional.

## End-to-End Testing

Run these after Phase 1 is stable so the full radio/archive pipeline exists.

### E2E 1: Default soundfont render

1. Configure the default MuseScore General / FluidR3-style soundfont path.
2. Generate a short section for a known preset.
3. Verify rendering reports FluidSynth, not internal synth, when the pack is installed.
4. Verify archive metadata records the soundfont pack and license id.

### E2E 2: Instrument-pool variation

1. Configure at least three instruments for bass, harmony, lead, and texture.
2. Generate multiple sections with different style presets.
3. Verify role bundles show different selected instruments across sections.
4. Listen to generated MP3s and confirm the timbral changes are audible.

### E2E 3: Role sub-vote inside global envelope

1. Create a vote round where global style sets tempo/key.
2. Cast role sub-votes for a contrasting bass or lead instrument.
3. Let conductor apply the winner.
4. Verify tempo/key remain from global style while selected role instrument changes inside that envelope.

### E2E 4: Time-signature presets

1. Generate a 4/4 section and verify playback/archive.
2. Generate a 3/4 admin preset and verify events fit the meter.
3. Generate a 6/8 admin preset and verify events fit the meter.
4. Attempt a public-vote odd-meter override and verify it is rejected or ignored.

### E2E 5: Legal/safe pack handling

1. Configure default MIT pack and generate audio successfully.
2. Try referencing a non-configured or restricted pack id in generation params.
3. Verify validation rejects it and falls back to the default pack.
4. Verify README and archive metadata do not claim unclear packs are deploy-safe.

## Manual QA Evidence to Capture

- Audio samples comparing at least three style presets before/after Phase 2.
- Archive JSON showing selected role instruments and soundfont metadata.
- MIDI file opened or probed to confirm valid channel/program assignments.
- Render log showing FluidSynth path when soundfont exists and internal fallback when it does not.
- README excerpt listing packs/tools and license caveats.

## Completion Notes

Do not add new roles in Phase 2. Do not bundle or commit soundfonts unless their license explicitly permits redistribution. Do not let LLM output or listener suggestions select arbitrary unconfigured instruments.
