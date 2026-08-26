# SpinSci — Marketing Website UI Kit

A high-fidelity, modular recreation of the SpinSci marketing site, built from the brand spec
(`/colors_and_type.css`) and the supplied logo. Cosmetic, not production logic — assemble the
components to mock pages, then lift patterns into real builds.

## Run it
Open `index.html`. It renders a full scrollable marketing page with working interactions:
- **Nav** turns from transparent → frosted white on scroll, links + "Book a demo" CTA.
- **Hero** with ambient mint wash, gradient display word, and a live scheduling-agent chat card that staggers its messages in.
- **Features** — 2-up light cards with hover lift (ring shadow deepens, −2px translate).
- **PlatformDark** — navy→teal gradient section with clickable agent tabs (Scheduling / Billing / Pharmacy / Referrals).
- **StatBand** — 3 dark stat cards (count-up on scroll-into-view) + 1 mint CTA card.
- **Testimonial** — asymmetric-radius dark quote card.
- **Resources** — 3-up blog cards.
- **Footer** — dark, with compliance line.
- **Demo modal** — opens from any "Book a demo" CTA; two-step form → success state.

## Files
| File | Exports | What |
|---|---|---|
| `primitives.jsx` | `SpinIcon`, `Eyebrow`, `IconBox`, `Button` | Atoms. Lucide-style 2px inline icons; pill buttons with circular icon suffix. |
| `Nav.jsx` | `Nav` | Sticky header, scroll-frosted. |
| `Hero.jsx` | `Hero` | Hero + animated `HeroCard` chat demo. |
| `Features.jsx` | `Features` | Feature grid + `FeatureCard`. |
| `PlatformDark.jsx` | `PlatformDark` | Dark tabbed agents section. |
| `StatBand.jsx` | `StatBand` | Stat cards with `useCountUp` + CTA. |
| `Sections.jsx` | `Testimonial`, `Resources`, `Footer` | Lower-page sections. |
| `index.html` | — | Assembles everything + demo modal. |

## How components share scope
Each `<script type="text/babel">` is isolated. Every component file ends with
`Object.assign(window, {...})` (or `window.X = X`) to publish to global scope so later
files and `index.html` can use them. Load order in `index.html` matters: `primitives.jsx` first.

## Conventions baked in
- Display headings: Noto Serif **300** with tight negative tracking. Never bold.
- Eyebrows: Sora 700 caps, +0.96px, violet (or white-on-dark via `onDark`).
- Cards: hairline border + **ring shadow** (`--shadow-card`), never drop shadow. Hover = deeper ring + −2px.
- Buttons: pill, circular icon suffix (`→`). Press = slight opacity dim, no scale.
- Color restraint: ink/navy anchors; violet + mint/teal only as accents and in icon boxes.

## Fidelity note
No SpinSci codebase or Figma was provided — these are faithful interpretations of the written
brand spec, not lifted source. Share real source to make them pixel-exact. Icons are Lucide-style
(2px outline) substitutes; swap in an in-house set if one exists.
