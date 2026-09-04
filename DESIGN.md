# Pitch Index Design System

## Visual world

Minimalist Monochrome translated for an operational MLB analytics workspace: authoritative editorial typography, pure black and paper white, sharp geometry, ruled structure, selective inversion, and measurement-led details. It should feel like a baseball scouting ledger designed by a museum-catalog studio, not a generic SaaS dashboard or a fashion cover pasted over a tool.

## Palette

- Paper: `#FFFFFF`
- Ink: `#000000`
- Muted paper: `#F5F5F5`
- Secondary ink: `#525252`
- Hairline: `#E5E5E5`
- No chromatic accents, gradients, soft shadows, or decorative elevation.

## Typography

- Display: Playfair Display, used only for identity and decisive numerical emphasis.
- Reading: Source Serif 4, used for explanations and table identities.
- Measurement: JetBrains Mono, used for labels, dates, units, filters, and technical evidence.
- Operational text never falls below 12px; body copy starts at 16px.
- The compact product header carries the identity. Repeated daily workflows must not sit below a full-screen hero.

## Layout and interaction

- Operate mode: the current task and next decision outrank spectacle.
- Fantasy is the default workspace. Models and Pitch Lab own separate summaries and evidence; their content does not leak into the Fantasy opening view.
- Major sections are divided by 4px rules; evidence rows use 1px borders. Corners are always square.
- Primary filters stay visible; secondary filters live in an Advanced disclosure.
- State changes are instant or at most 100ms. Keyboard focus uses a 3px black outline with offset.

## Monochrome data graphics

- Never distinguish series with two near-black fills.
- Primary series: solid black.
- Comparison series: white fill with black 1.5–2px outline.
- A third series, when necessary: sparse diagonal hatching plus black outline.
- Direct labels and explicit deltas supplement legends; pattern or shape always provides a non-color channel.

## Responsive contract

- The page itself never scrolls horizontally.
- Workspace tabs remain fully visible at 390px.
- Wide tables and charts scroll only inside labelled, keyboard-focusable regions with a visible continuation cue.
- KPI context moves below the value rather than being clipped beside it.
