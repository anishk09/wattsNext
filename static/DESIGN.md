# Watt'sNext — Design Notes

Chosen via the `ui-ux-pro-max` skill (`Minimalism & Swiss Style` + `Corporate Trust`
typography), adapted from a landing-page pattern to a single-column concierge
chat with inline data cards.

## Why

A storm outage product talks to someone who is stressed and possibly about to
lose power. The UI should read as a calm utility tool, not a generic AI
chatbot: restrained color, high contrast, no playful illustration, numbers
presented as labeled facts rather than conversational prose.

## Palette (v3 — sampled from aepohio.com)

v2 was AEP-*inspired* but used a generic navy/bright-blue/gold trust
palette pulled from the challenge brief's text description. v3 replaces it
with colors actually sampled from a screenshot of the real AEP Ohio site
(aepohio.com): red CTAs and active states, charcoal text, a white header
over light-gray panels, and four accent colors lifted from the site's own
quick-link icons (blue/orange/teal/green). This is a palette *inspired by*
AEP's site, never its logo or wordmark — "Ohio Power Company" and the
chevron mark are not reproduced anywhere; the product name and mark stay
Watt'sNext throughout, so the result reads as "a prototype in AEP's visual
language," not an official AEP page.

**Risk-band colors stay a distinct hue family from the brand red** — a
risk chip must never be mistaken for brand chrome. High risk uses a dark
maroon (not the brand red), always paired with a warning-triangle icon and
the word "risk" in text, never color alone.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-primary` | `#D2352B` (red) | `#D2352B` (same) | buttons, active tab, links, thin rule under topbar |
| `--color-link` | `#D2352B` | `#E8626B` | plain-text links only (dark mode needs a lighter tint — see below) |
| `--color-accent` | `#1F5FA8` (blue) | `#4A8FD4` | secondary accent |
| `--color-highlight` | `#B35A12` (darkened orange) | `#E0975A` | sparing highlight (e.g. "in progress" badge) |
| `--color-destructive` | `#7A1620` (maroon) | `#E8A0A6` | safety warnings, offline-mode banner |
| `--color-background` | `#FFFFFF` | `#1C1C1C` | page background |
| `--color-panel` | `#F2F2F2` (light gray) | `#262626` | dashboard section panels |
| `--color-card` | `#FFFFFF` | `#2E2E2E` (charcoal) | message + data cards |
| `--color-foreground` | `#2E2E2E` (charcoal) | `#F2F2F2` | body text |
| `--color-muted` | `#F2F2F2` | `#3A3A3A` | evidence-tag chips, muted lanes |
| `--color-muted-foreground` | `#5A5A5A` | `#B5B5B5` | secondary text, tag labels |
| `--color-border` | `#D9D9D9` | `#454545` | card and input borders |
| `--color-risk-high` | `#7A1620` (maroon) | `#E8A0A6` | risk band High |
| `--color-risk-moderate` | `#B35A12` (orange) | `#F2994A` | risk band Moderate |
| `--color-risk-low` | `#3F7A1E` (green) | `#7FC24A` | risk band Low |
| `--color-icon-blue` | `#1F5FA8` | same | icon-circle fill |
| `--color-icon-orange` | `#B35A12` | same | icon-circle fill |
| `--color-icon-teal` | `#0E6B7A` | same | icon-circle fill |
| `--color-icon-green` | `#3F7A1E` | same | icon-circle fill |

**Contrast, worked through rather than guessed:**
- White-on-red button text (`#D2352B` fill): **4.9:1**, passes, same value
  in both modes since it's the same hex — this is *why* the brand red can
  stay identical across light/dark while most of this app's other tokens
  can't: a filled button's internal contrast never depends on the page
  background around it.
- Red *as plain text* on the dark charcoal background only reaches
  **3.5:1** — fails AA for text (though it's fine as a non-text focus-ring
  indicator, which only needs 3:1). `--color-link` exists solely to give
  dark-mode anchor text a lighter red (`#E8626B`, **5.2:1**) without
  touching every filled button that correctly keeps the true brand red.
- The screenshot's lighter orange (`~#E07A1F`, **3.0:1**) and teal
  (`~#1A9BB0`, **3.3:1**) both fail 4.5:1 as text or as a white glyph on a
  filled circle. Darkened to `#B35A12` (**4.8:1**) and `#0E6B7A`
  (**6.2:1**) respectively — still read as "orange" and "teal," just a
  shade deep enough to carry a white icon or text. Blue (`#1F5FA8`,
  **6.4:1**) and green, once similarly darkened to `#3F7A1E` (**5.2:1**,
  from a screenshot green that itself only hit 2.9:1), needed no further
  change for light mode.
- Dark-mode risk colors are lighter tints of the same hues (e.g. risk-high
  `#E8A0A6` instead of the light-mode `#7A1620`) so they stay legible
  against the dark charcoal card background (**7–8:1** each) — a dark
  maroon that works on white is nearly invisible on `#1C1C1C`.

## Typography

**Barlow Condensed** (700) for headings — bold, condensed, uppercase,
matching the screenshot's hero and nav type — **Barlow** for body text.
Short action labels (Send, New, the view toggle, dialog buttons) are
uppercase too, echoing the site's "LOG IN" / "ACCEPT ALL" buttons; longer
sentence-style text (starter questions, what-if chips) stays normal case
for readability. Base size 16px, line-height 1.5, type scale 14/16/20/28px.

## Spacing & shape

8px base unit (8/16/24/32/48). 10px card radius — soft enough to feel
approachable, not so round it looks playful. Inline evidence tags use a
4px radius pill, visually distinct from message bubbles.

## Components

- **Icon circles**: simple hand-drawn outline glyphs (warning triangle, info,
  check, clock, bell, shield, checklist, list) on a colored circle, white
  stroke on fill — echoes the AEP site's four circled quick-link icons.
  Used on the risk chip (in place of a plain color dot — band is never
  color alone) and as a small marker before every dashboard section and
  three-lane header.
- **Risk chip**: icon circle (warning/info/check, colored by band) + band +
  confidence, inline with the message.
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
