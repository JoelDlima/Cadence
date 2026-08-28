# UI/UX Guidelines (ops console)

Mode: Hackathon Sprint · Research date: 2026-08-22 · Lightweight

## Positioning

The console is mission-control tooling for watching the engine work - not a consumer
product. Clarity of the decision log beats decoration. One page, four zones.

## Core flows

1. Journeys list (live): id, subscriber, state badge, root cause, last event age. Polls local API every 2s.
2. Journey detail: vertical event timeline replayed as a scrubber animation - the audit-trail money shot for the video.
3. Metrics strip: recovered INR, journeys by state, fast-path percentage, LLM calls today, violations (always 0 expected).
4. Kill switch: explicit two-step confirm; state visible at all times.

## Visual direction (deliberate, anti-generic)

Dark operations-terminal aesthetic: near-black surface, one accent (signal green for
recovered, amber for deferred/vetoed, red for terminal-failure), monospace-forward type
(Geist Mono/IBM Plex Mono class) paired with a grotesk for headings. Dense tabular data,
hairline dividers, no gradient meshes, no glassmorphism.

## Motion rules (kit-mandated)

- Micro-interactions 150-300ms, ease-out arrivals; transform/opacity only.
- Staggered card reveals on list mount (30-60ms stagger); state-badge transitions; scrubber plays timeline with eased step reveals.
- One easing curve site-wide; `prefers-reduced-motion` variant: crossfade/instants only.
- Mobile Lighthouse: LCP < 2.5s, CLS ~0, INP < 100ms (static assets, tiny JS).

## States

Empty: "No journeys yet - fire the demo webhook" with the exact curl shown. Failure:
inline error line, never stack traces. Loading: skeleton rows matching final layout.

## Explicitly not building

Auth screens, settings pages, charts beyond the metrics strip, responsive tables beyond 360px.
