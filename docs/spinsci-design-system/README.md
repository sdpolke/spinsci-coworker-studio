# SpinSci Design System

*Inspired by the SpinSci.ai visual language — clean, intelligent, and trustworthy.*

> **Mission:** Remove every point of friction in patient access, establishing exceptional patient experiences as the standard.

---

## What SpinSci is

SpinSci builds **healthcare patient-access automation** — AI agents and contact-center software that sit on top of EHR systems (Epic, Cerner/Oracle Health, etc.) to handle scheduling, registration, billing, pharmacy refills, referrals, and patient communication. The product story is about removing friction for patients and offloading repetitive work from care teams, framed in a calm, authoritative, metric-led voice.

Core product surfaces represented in this system:
- **Marketing website** (spinsci.ai) — the primary surface recreated here as a UI kit. Dark navy hero, serif display headlines, mint/violet accents, pill CTAs, stat grids, and dark testimonial/platform sections.

This design system was built to let design agents produce well-branded SpinSci interfaces, slides, and assets — either throwaway mocks or production-quality HTML.

---

## Sources

- **Brand spec** — provided directly by the user (full SpinSci Design System markdown: color palette, type scale, spacing, components, motion). This is the authoritative token source and is reproduced faithfully in `colors_and_type.css`.
- **Logo** — `uploads/spinsci.svg` (wordmark + gradient mark). Copied to `assets/spinsci-logo.svg` and a white variant `assets/spinsci-logo-white.svg`.
- **Display font** — `uploads/NotoSerif-Regular.ttf`, copied to `fonts/`.
- **Reference site** — spinsci.ai (visual language inspiration; not directly imported).

No codebase or Figma file was provided — the system is derived from the written brand spec plus the supplied logo and font. See **Caveats** at the bottom.

---

## Content fundamentals

**Voice mirrors the visual restraint: confident, terse, metric-led.**

- **Headlines are statements, not questions.** Declarative and short. "Remove every point of friction in patient access." Never "Want to reduce friction?"
- **No exclamation marks.** Energy comes from precision, not punctuation.
- **Metric-led.** Lead with numerics: `165`, `400M+`, `60M`. Stats carry the proof; prose stays out of the way.
- **Person:** Speaks to the buyer as **"you"** ("your patients," "your care teams") and refers to the company as **SpinSci** or **we** sparingly. Patient-facing copy is warm and plain.
- **Section labels (eyebrows)** are short fragments in **ALL CAPS** — "PATIENT ACCESS", "THE PLATFORM", "WHY SPINSCI". Always violet, always tracked out.
- **Casing:** Sentence case for headlines and body. ALL CAPS reserved for eyebrows and stat sub-labels only. No Title Case Everywhere.
- **No emoji.** Ever. The brand uses line icons inside icon boxes instead (see Iconography).
- **Vibe:** Quiet confidence. Clinical-grade trust without coldness — the serif display and mint accent add warmth. Avoid hype words ("revolutionary", "game-changing"); prefer concrete outcomes ("reduce hold times", "automate refill requests").

Example phrasing:
> EYEBROW: `PATIENT ACCESS`
> Headline: *Every patient interaction, handled with care.*
> Body: SpinSci agents resolve scheduling, billing, and pharmacy requests across your existing EHR — no rip-and-replace.
> Stat: `400M+` patient interactions automated.

---

## Visual foundations

**Overall feel:** Editorial, premium, calm. Lots of white space; a thin light serif doing the display work; a clean geometric sans (Sora) for everything functional. Color is used sparingly — navy/ink anchors, with violet and mint as small bright accents.

**Color**
- Anchored by **ink `#091322`** and **navy `#122643`** (text + dark sections + primary buttons).
- Page background is white; secondary sections use warm off-white **surface `#F7F6F5`**.
- Accents are deployed in small doses: **violet `#7759D9`** for eyebrows/tags/highlights, **teal `#04867C`** and **mint `#5CE0B0`** for success states, icons, and data-vis. Subtle 20%-alpha tints (`--color-violet-subtle`, `--color-mint-subtle`) fill icon boxes and badges.
- Imagery/illustration skews **cool with a warm mint glow** — never saturated, never warm-orange. Think clinical-clean with a soft teal-green light.

**Type**
- Display = **Noto Serif at weight 300** with tight negative tracking (−3.2px at 80px). Never bold display. This light serif is the single most recognizable brand move.
- UI/body = **Sora 400–700**. Eyebrows are Sora 700, 12px, ALL CAPS, +0.96px tracking, violet.
- A gradient-fill heading treatment (`--gradient-heading`, violet→navy) is used occasionally on key display words.

**Spacing & layout**
- Base-8 grid, 4px micro unit. Section vertical rhythm: **80px** desktop / 48px mobile. Hero: 96px.
- Max content width **1200px**, centered; **40px** desktop gutter / 20px mobile.
- 12-column grid, 24px gutters. Feature grids 2-up, stat rows 4-up (3 stat + 1 CTA), blog rows 3-up.

**Backgrounds**
- Mostly flat white or flat surface. Hero uses a **slow ambient radial mint-to-white wash** drifting from top-right (8s loop). Dark "platform" sections use a deep navy→teal-purple diagonal gradient. No photographic full-bleed backgrounds, no repeating textures, no noise/grain.

**Borders, radius & cards**
- Generous rounding: cards `16px`, large feature cards `24px`, pills `100px`. Some cards use **asymmetric rounding** (flatter top `16px`, rounder bottom `32px`) — a signature on testimonial cards.
- Cards do **not** use drop shadows. They use a **soft outer ring** — `rgba(18,38,67,0.04) 0 0 0 4px` — that thickens on hover. Hairline borders `rgba(9,19,34,0.10)`.
- Modals/popovers are the exception: real drop shadow `0 24px 48px rgba(9,19,34,0.12)`.

**Motion**
- Subtle and purposeful. Card hover: `translateY(-2px)` + ring deepens, 200ms ease. Button hover: `opacity: 0.9`, 150ms. Section entrance: fade-up (`translateY(16px)→0`, opacity 0→1) over 500ms with `cubic-bezier(0.16,1,0.3,1)`. Numbers count up on scroll-in. Chat bubbles stagger-fade 100ms apart. No bounce, no spring overshoot.

**Press states**
- Buttons darken/dim slightly (opacity or a touch darker), no shrink-scale by default. Keep it understated.

**Transparency & blur**
- Nav goes from transparent over the hero to `rgba(255,255,255,0.95)` with a subtle blur on scroll. Alpha tints used for icon boxes, badges, and on-dark surfaces (`rgba(255,255,255,0.05)` cards on dark).

---

## Iconography

- **Style:** outline / line icons, **2px stroke weight**, rounded joins. No filled/duotone icon sets.
- **Color:** icons inherit **teal `#04867C`** or **violet `#7759D9`** depending on the section context (teal in product/success contexts, violet in marketing/highlight contexts).
- **Size:** 20×20 standard, 24×24 for feature icons.
- **Container:** icons live inside an **Icon Box** — a 32×32 rounded-8px square filled with a 20%-alpha tint (`--color-mint-subtle` or `--color-violet-subtle`).
- **No emoji, no unicode-as-icon.** Buttons carry a small circular icon *suffix* (an arrow `→` or plus in a circle) to signal forward motion — a SpinSci signature.

**Implementation:** No proprietary icon font or SVG sprite was provided in the source materials. This system links **[Lucide](https://lucide.dev)** (`lucide@latest` via CDN) as the substitute — Lucide is a clean 2px-stroke outline set that matches the described style. **This is a substitution; flag for the user** if SpinSci has an in-house icon set to swap in. Use `stroke-width="2"` and color icons with `--color-teal` / `--color-violet`.

The brand **logo** (`assets/spinsci-logo.svg`) is a wordmark in logo-ink `#1C0236` paired with a gradient swirl mark (violet→periwinkle→mint). Use `spinsci-logo-white.svg` on dark/navy backgrounds.

---

## Components

Compiled into the design-system bundle (`window.SpinSciDesignSystem_529811`), source in `ui_kits/website/`:
- **Primitives** — `SpinIcon`, `Eyebrow`, `IconBox`, `Button`
- **Nav** — sticky marketing header, scroll-frosted
- **Hero** — hero section with animated scheduling-agent chat card
- **Features** — 2-up feature-card grid
- **PlatformDark** — dark tabbed AI-agents section
- **StatBand** — count-up stat cards + mint CTA
- **Sections** — `Testimonial`, `Resources`, `Footer`

## Index / manifest

Root files:
- `README.md` — this file (context, content & visual foundations, iconography, manifest).
- `colors_and_type.css` — all design tokens as CSS custom properties + semantic type classes. **Start here when building.**
- `SKILL.md` — Agent-Skills-compatible entry point.
- `fonts/` — self-hosted **Noto Serif** (display, full weight range) and **Sora** (UI) `.ttf` files, wired in `colors_and_type.css`.
- `assets/spinsci-logo.svg`, `assets/spinsci-logo-white.svg` — brand marks.
- `preview/` — Design System tab cards (colors, type, spacing, components).
- `ui_kits/website/` — marketing-site UI kit (README, index.html, JSX components).

To build a SpinSci interface: link `colors_and_type.css` + the Sora Google-Font + Lucide CDN, wrap your root in `.ds-scope`, and pull components/patterns from `ui_kits/website/`.

---

## Caveats

- **No codebase or Figma** was provided — everything derives from the written brand spec + logo + font. Components in the UI kit are faithful interpretations of the spec, not lifted from production source. If a real codebase or Figma exists, share it and the kit can be made pixel-exact.
- **Sora** is the UI font and is now **self-hosted** in `fonts/` (the brand spec referenced it; the user supplied the files). The `<link>` to Google Fonts in the preview/kit HTML is now redundant but harmless.
- **Icons** use Lucide via CDN as a substitute for an unspecified in-house set (see Iconography).
- Stat numbers (`165`, `400M+`, `60M`) in mocks are illustrative placeholders pulled from the spec's examples — replace with real figures before any external use.
