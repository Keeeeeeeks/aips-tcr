# Phase 3 Implementation Plan: About Page and Collapse Framing

Date: 2026-05-01
Status: Planned
Design source: `docs/superpowers/specs/2026-05-01-aips-radio-deployment-design.md`

## Goal

Ship the public conceptual layer for the AIPS radio project: a hybrid institutional/experiment-log About page, formal legal disclaimer, and behavior-based collapse logging that treats listener inactivity/convergence as the primary artistic signal.

## Acceptance Criteria

Phase 3 is complete when:

1. The public site has an About page matching the current Liquid Glass/Y2K Aero visual style.
2. The About page explains Resoworks, the AIPS Summit, the Chinese Room framing, and LLMs as procedural imitations of understanding.
3. The About page states that the original experiment has been adapted into an ongoing radio where people vote on what style the next two minutes should emulate.
4. The page includes the three experiment questions.
5. The page defines collapse behaviorally as people stopping their nudges/votes/suggestions.
6. The page uses a hybrid tone: credible art-label/institutional explanation first, stranger experiment-log texture second.
7. The legal disclaimer covers parody/commentary, non-affiliation, no endorsement, no revenue intent, no transfer of rights, and all rights reserved language.
8. Backend behavior logging records vote frequency, repeated choices, suggestion rate, inactivity periods, and convergence around one option.
9. Admin view exposes collapse/logging signals without presenting them as strict scientific proof.
10. README includes the conceptual framing and open-source disclaimer/secrets hygiene notes.

## Implementation Steps

### 1. Draft About page content

- Write concise institutional framing:
  - project name,
  - Resoworks context,
  - AIPS Summit context,
  - Chinese Room/LLM framing,
  - radio adaptation.
- Write experiment-log layer:
  - cycles,
  - style imitation,
  - collapse,
  - listener tolerance,
  - ambiguity between success, middle-ground drift, disuse, and shared delusion.
- Keep the copy readable; avoid turning the whole page into dense legal or academic prose.

### 2. Add legal disclaimer block

- Include formal language for:
  - parody/commentary/experimental purpose,
  - no affiliation with or endorsement by referenced artists/rights holders,
  - all rights reserved to respective owners,
  - no revenue intent,
  - no transfer or claim of ownership,
  - no intent to infringe or violate applicable laws.
- Place the disclaimer on About and link to it from archive/style-reference surfaces.
- Avoid presenting this as legal advice.

### 3. Build About page in existing style

- Reuse current Liquid Glass/Y2K Aero typography, panels, rails, and visual language.
- Add navigation from the main radio page to About and Archive.
- Ensure the page works as a static Vercel-served page using the same asset/config pattern as the public frontend.

### 4. Add behavior logging model

- Extend backend state to record per-round behavior:
  - vote count,
  - unique anonymous voter count,
  - repeated winning option,
  - suggestion count,
  - approved suggestion count,
  - inactivity window duration,
  - convergence streak around one option.
- Store logs per session/round and include summary in archive metadata where appropriate.
- Avoid collecting unnecessary personal data; use aggregate/cookie-derived counts rather than identities.

### 5. Add admin collapse signal view

- Add a backstage admin panel or endpoint showing:
  - current vote frequency,
  - latest inactivity window,
  - repeated-choice streak,
  - suggestion rate,
  - rough collapse interpretation.
- Label the interpretation as artistic/behavioral, not scientific or diagnostic.

### 6. Update README

- Add project framing:
  - Resoworks/AIPS Summit,
  - Chinese Room meditation,
  - voting radio adaptation,
  - collapse definition.
- Add open-source caution:
  - no secrets,
  - no private soundfonts,
  - soundfont/license attribution,
  - legal disclaimer pointer.

## Unit and Integration Tests

- About page route/static file exists and includes required content markers.
- Disclaimer text includes all required categories.
- Behavior logger records vote count after votes.
- Behavior logger records suggestion rate after suggestions.
- Inactivity detector records inactivity after a configured quiet window.
- Repeated-choice/convergence logic increments when the same option wins consecutive rounds.
- Admin collapse endpoint/view returns aggregate metrics only, not secrets or raw admin state.
- README contains required project framing and open-source hygiene sections.

## End-to-End Testing

Run these after Phases 1 and 2 are stable.

### E2E 1: Public About page

1. Serve the frontend.
2. Open the About page from the main navigation.
3. Verify the page visually matches the current style.
4. Verify it mentions Resoworks, AIPS Summit, Chinese Room, ongoing voting radio, and the three experiment questions.
5. Verify the formal disclaimer block is present.

### E2E 2: Archive/style disclaimer path

1. Open an archive entry that references a style.
2. Verify there is a visible link or nearby reference to the disclaimer/About page.
3. Verify no archive page implies affiliation or endorsement by referenced artists.

### E2E 3: Collapse logging from voting behavior

1. Start a fresh session with an active voting round.
2. Cast votes across several rounds, repeatedly selecting the same option.
3. Verify backend logs vote frequency and repeated-choice streak.
4. Stop voting for a configured quiet window.
5. Verify inactivity period is logged.
6. Open admin view and verify aggregate collapse signals appear.

### E2E 4: Suggestion-rate logging

1. Submit multiple safe suggestions.
2. Submit at least one rejected/quarantined suggestion.
3. Verify suggestion rate and approval/rejection counts update.
4. Verify no raw unsafe suggestion text is exposed publicly.

### E2E 5: README/open-source check

1. Inspect README in the public repo state.
2. Verify it explains project purpose, architecture, music tools, soundfonts, licenses, and secrets policy.
3. Verify `.env.example` exists and `.env` does not.
4. Verify no admin secret, API key, server credential, generated cookie/session data, or legally ambiguous soundfont is present in tracked files.

## Manual QA Evidence to Capture

- Screenshot of About page top section and disclaimer block.
- JSON/admin screenshot of aggregate collapse metrics after simulated rounds.
- Archive page screenshot showing disclaimer path.
- README excerpt covering soundfonts/tools and secrets policy.

## Completion Notes

Phase 3 should not overclaim scientific measurement. Collapse is the project's artistic interpretation of listener behavior. Keep raw listener identity data out of the feature unless a later privacy review explicitly approves it.
