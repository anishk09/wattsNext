# Watt'sNext — Design Notes

Chosen via the `ui-ux-pro-max` skill (`Minimalism & Swiss Style` + `Corporate Trust`
typography), adapted from a landing-page pattern to a single-column concierge
chat with inline data cards.

## Why

A storm outage product talks to someone who is stressed and possibly about to
lose power. The UI should read as a calm utility tool, not a generic AI
chatbot: restrained color, high contrast, no playful illustration, numbers
presented as labeled facts rather than conversational prose.

## Palette

Trust blue + slate neutrals + a warm amber for "pay attention" states.
Destructive red reserved for safety-critical text only (never decorative).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-primary` | `#2563EB` | `#60A5FA` | links, primary buttons, risk=Low |
| `--color-accent` | `#D97706` | `#FBBF24` | risk=Moderate, "what-if" chips |
| `--color-destructive` | `#DC2626` | `#F87171` | risk=High, safety warnings only |
| `--color-background` | `#F8FAFC` | `#0F172A` | page background |
| `--color-card` | `#FFFFFF` | `#1E293B` | message + data cards |
| `--color-foreground` | `#1E293B` | `#E2E8F0` | body text |
| `--color-muted` | `#E9EFF8` | `#243244` | evidence-tag chips, muted lanes |
| `--color-muted-foreground` | `#475569` | `#94A3B8` | secondary text, tag labels |
| `--color-border` | `#E2E8F0` | `#334155` | card and input borders |

All text/background pairs verified ≥ 4.5:1 in both modes.

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

## Motion & accessibility

`prefers-reduced-motion` disables the typing-indicator bounce and chip
transitions (opacity/transform swapped for instant state). All interactive
elements keep a visible focus ring (`--color-ring`, 2px, offset). New
assistant messages announce via a single `aria-live="polite"` region on the
conversation log, not per-element.
