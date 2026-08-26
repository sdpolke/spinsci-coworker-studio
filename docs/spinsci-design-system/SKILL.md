---
name: spinsci-design
description: Use this skill to generate well-branded interfaces and assets for SpinSci, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `README.md` file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Quick start
- `colors_and_type.css` — all design tokens (colors, type scale, spacing, radius, shadow, motion) as CSS custom properties + semantic type classes, plus self-hosted `@font-face` for Noto Serif (display) and Sora (UI). Link this first; wrap your root in `.ds-scope`.
- `fonts/` — Noto Serif + Sora `.ttf` files (referenced by the CSS).
- `assets/` — `spinsci-logo.svg` (light bg) and `spinsci-logo-white.svg` (dark bg).
- `ui_kits/website/` — modular React/JSX recreation of the marketing site (Nav, Hero, Features, PlatformDark, StatBand, Testimonial, Resources, Footer + demo modal). Read its README.
- `preview/` — small specimen cards for every token group.

## The brand in one breath
Quiet, editorial, trustworthy healthcare-AI. Light **Noto Serif 300** display with tight negative
tracking; **Sora** for everything functional. Ink/navy anchors with sparing violet + mint/teal
accents. Pill buttons with a circular icon suffix. Cards use a soft **ring shadow**, never a drop
shadow. Copy is terse, confident, metric-led, sentence case, no emoji, no exclamation marks.
