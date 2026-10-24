# Watt'sNext — Design Notes

Chosen via the `ui-ux-pro-max` skill (`Minimalism & Swiss Style` + `Corporate Trust`
typography), adapted from a landing-page pattern to a single-column concierge
chat with inline data cards.

## Why

A storm outage product talks to someone who is stressed and possibly about to
lose power. The UI should read as a calm utility tool, not a generic AI
chatbot: restrained color, high contrast, no playful illustration, numbers
presented as labeled facts rather than conversational prose.

## Palette (AEP-inspired, v2)

Switched from the initial generic trust-blue palette to colors pulled from
the AEP challenge brief itself — deep navy, bright blue, gold, pale blue, a
thin red accent — applied to both the chat and the new "Storm activity"
dashboard so the whole product reads as one system. This is a palette
*inspired by* AEP's brand colors, not the AEP logo or wordmark; the product
name and mark are Watt'sNext throughout.

**Risk-band colors are intentionally a separate hue family** (green/
orange/red) from the brand palette — a risk chip must never be mistaken
for brand chrome, and vice versa.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-primary` | `#1B365D` (navy) | `#29A8DF` (bright blue) | buttons, links, headers |
| `--color-accent` | `#29A8DF` | `#29A8DF` | secondary accents, active tab |
| `--color-highlight` | `#F5B335` (gold) | `#F5B335` | sparing highlight (e.g. "in progress" badge) |
| `--color-destructive` | `#D7262E` | `#F87171` | safety warnings, offline-mode banner — used sparingly |
| `--color-panel` | `#E8F1F8` (pale blue) | `#16314F` | dashboard section panels |
| `--color-background` | `#F8FAFC` | `#0F172A` | page background |
| `--color-card` | `#FFFFFF` | `#1E293B` | message + data cards |
| `--color-foreground` | `#1E293B` | `#E2E8F0` | body text |
| `--color-muted` | `#E8F1F8` | `#16314F` | evidence-tag chips, muted lanes |
| `--color-muted-foreground` | `#475569` | `#94A3B8` | secondary text, tag labels |
| `--color-border` | `#D7E3EE` | `#2B4A6B` | card and input borders |
| `--color-risk-low` | `#15803D` | `#4ADE80` | risk band Low |
| `--color-risk-moderate` | `#C2410C` | `#FB923C` | risk band Moderate |
| `--color-risk-high` | `#B91C1C` | `#F87171` | risk band High |

The bright blue (`#29A8DF`) fails AA as white-on-blue button text (~2.7:1),
so it's never used as a filled-button background in light mode — navy
(`#1B365D`, 12:1 against white) carries that role there. In dark mode the
roles flip: bright blue reads well as text/accent against the near-black
background (~6:1), so it becomes the primary token and navy drops out of
the text palette entirely (too close to the dark background to read).
Same reasoning kept `--color-highlight` text (gold) off light backgrounds
(~1.8:1 against white) — gold is navy-on-gold in light mode, gold-on-dark
in dark mode. All text/background pairs are verified ≥ 4.5:1 in both modes.

## Typography

**Corporate Trust** pairing: **Lexend** for headings/labels (designed for
reading-speed accessibility), **Source Sans 3** for body text. Base size
16px, line-height 1.5, type scale 14/16/20/28px.

## Spacing & shape

8px base unit (8/16/24/32/48). 10px card radius — soft enough to feel
approachable, not so round it looks playful. Inline evidence tags use a
4px radius pill, visually distinct from message bubbles.

## Components

- **Risk chip**: colored dot + band + confidence, inline with the message.
- **Restoration range bar**: a horizontal bar spanning low→high hours, labeled
  "Model estimate — not confirmed by the utility."
- **Three-lane layout**: Estimate / Confirmed by utility (always empty, shown
  explicitly) / What you can do — equal-width on desktop, stacked on mobile.
- **SMS bubbles**: alert previews render as phone-style bubbles (rounded,
  tail-less, timestamp caption) to visually separate "a message you'd
  receive" from "the assistant talking to you now."
- **Evidence tags**: small pill on every number (`Source data` / `Assumption`
  / `Model estimate` / `Not available`), clicking opens a dialog with the
  tag's note — sourced from the same tool-call payload already in the
  message, no extra request.

- **Storm activity dashboard**: a second view of the same session (toggle in
  the topbar, chat is never replaced), titled "Storm replay" — never "Live"
  — with a persistent honesty strip above the fold. Shows the risk chip,
  restoration range (with before/after when a what-if has changed it), a
  restoration step timeline (crew + status per job, from the scheduler),
  an always-visible 4-row alert matrix (triggered/not yet, this session),
  and a newest-first session event feed. The same what-if chips sit below
  both views and drive whichever one is open.

## Motion & accessibility

`prefers-reduced-motion` disables the typing-indicator bounce and chip
transitions (opacity/transform swapped for instant state). All interactive
elements keep a visible focus ring (`--color-ring`, 2px, offset). New
assistant messages announce via a single `aria-live="polite"` region on the
conversation log, not per-element.
