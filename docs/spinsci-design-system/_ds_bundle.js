/* @ds-bundle: {"format":4,"namespace":"SpinSciDesignSystem_529811","components":[{"name":"Features","sourcePath":"ui_kits/website/Features.jsx"},{"name":"Hero","sourcePath":"ui_kits/website/Hero.jsx"},{"name":"Nav","sourcePath":"ui_kits/website/Nav.jsx"},{"name":"PlatformDark","sourcePath":"ui_kits/website/PlatformDark.jsx"},{"name":"SpinIcon","sourcePath":"ui_kits/website/Primitives.jsx"},{"name":"Eyebrow","sourcePath":"ui_kits/website/Primitives.jsx"},{"name":"IconBox","sourcePath":"ui_kits/website/Primitives.jsx"},{"name":"Button","sourcePath":"ui_kits/website/Primitives.jsx"},{"name":"Primitives","sourcePath":"ui_kits/website/Primitives.jsx"},{"name":"Testimonial","sourcePath":"ui_kits/website/Sections.jsx"},{"name":"Resources","sourcePath":"ui_kits/website/Sections.jsx"},{"name":"Footer","sourcePath":"ui_kits/website/Sections.jsx"},{"name":"Sections","sourcePath":"ui_kits/website/Sections.jsx"},{"name":"StatBand","sourcePath":"ui_kits/website/StatBand.jsx"}],"sourceHashes":{"doc-page.js":"f52ae9c02fca","ui_kits/website/Features.jsx":"972c0bba8d3c","ui_kits/website/Hero.jsx":"88fd5fa8d4a7","ui_kits/website/Nav.jsx":"55225fc9c9dc","ui_kits/website/PlatformDark.jsx":"ef54963b40b5","ui_kits/website/Primitives.jsx":"866e9b14c380","ui_kits/website/Sections.jsx":"0abe9bc73a72","ui_kits/website/StatBand.jsx":"f95e40a50d25"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.SpinSciDesignSystem_529811 = window.SpinSciDesignSystem_529811 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// doc-page.js
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)
// Copied omelette starter. Re-running copy_starter_component with this kind overwrites this file with the latest version (page content is unaffected).
/* BEGIN USAGE */
/**
 * <doc-page> — paged-document shell for printable HTML.
 *
 * FIRST, decide how the document paginates — up front, before building:
 *
 * - FLOWING document (the default): write the whole document as one
 *   normal HTML flow inside <doc-page>; the browser's print engine
 *   splits it onto pages at export. Use for long-form documents with a
 *   single text flow: reports, memos, letters, essays.
 * - EXPLICIT pagination: a fixed set of pre-paginated pages, one
 *   <section class="page"> child per page. Use when the user asks for a
 *   specific page count, or the design implies one: a one-page resume, a
 *   two-sided flier, a poster, a certificate, a brochure — any richly
 *   laid-out document without a single text flow.
 * - If in doubt, ask the user as part of the build.
 *
 * PAGE SIZING — paper differs by country (letter vs A4), so the printed
 * sheet is not one fixed truth:
 * - FLOWING documents pin NO paper size: the print engine paginates
 *   onto the user's real paper, and the content reflows to it.
 * - EXPLICITLY PAGINATED documents print each page at a FIXED page box
 *   with overflow hidden — letter by default, size="a4" for a clearly
 *   metric user, the user's chosen paper when they export. Design each
 *   page to FILL that box, fitting letter and A4 alike without overlap.
 * - width/height pin an explicit fixed size, ONLY when the user gives
 *   one.
 * Never write your own @page rule or hard-code paper dimensions in the
 * content.
 *
 * Sizing modes (attributes):
 *   (none)                      — portrait: flowing docs use the user's
 *           paper; explicitly paginated pages use the named size box
 *           (letter unless size="a4")
 *   orientation="landscape"     — the same, landscape
 *   width / height              — explicit fixed size, ONLY when the user
 *           gives one (e.g. width="22in" height="30in" for a 22×30
 *           poster): the page IS the design's size, printed at true
 *           dimensions (or scaled onto the user's paper at print time).
 *           Any absolute CSS length: px/in/mm/cm/pt/pc.
 * The component announces the chosen mode to the host app at runtime (a
 * meta tag it injects), so the print path can inject the user's true
 * paper size.
 *
 * On screen the document renders on a desk background: a flowing
 * document as one tall scrolling sheet (Google Docs' pageless view);
 * explicitly paginated documents as one card per page.
 *
 * EXPLICIT pagination usage:
 *   <style>doc-page:not(:defined){visibility:hidden}</style>
 *   <doc-page>
 *     <section class="page" id="p1">…one page's design…</section>
 *     <section class="page" id="p2">…</section>
 *   </doc-page>
 *   <script src="doc-page.js"></script>
 * How the page box works, concretely: each .page prints as ONE full-bleed
 * sheet at a FIXED physical size — letter by default (set size="a4" for
 * a clearly metric user), the user's chosen paper when they export —
 * with overflow hidden. Nothing scrolls and nothing reflows onto a next
 * sheet: content that misses the box is CLIPPED. Design each page to
 * FILL that page box, and to fit it — letter and A4 alike — without
 * overlap. Each page is a size container; don't size anything in
 * viewport units (they track the window, not the page), and never set
 * width or height on the .page section itself (the component sizes the
 * page box; an authored height like 100% is meaningless at print and is
 * overridden). The component owns the page box, the screen card chrome,
 * and the page breaks (never add your own break-before/after). Don't mix
 * .page sections with flowing content or header/footer slots in the same
 * document.
 *
 * FLOWING usage:
 *   <style>doc-page:not(:defined){visibility:hidden}</style>
 *   <doc-page margin="0.75in">
 *     <h1>Title</h1>
 *     <p>…body…</p>
 *   </doc-page>
 *   <script src="doc-page.js"></script>
 * There is no manual page-splitting — the browser's print engine
 * paginates at export. Standard break-hygiene rules (`break-inside:
 * avoid` on figures, code blocks, images and table rows; `orphans/
 * widows: 3`) are applied so paragraphs and groups split cleanly. On
 * screen and at print, headings default to `text-wrap: balance` and
 * body text to `text-wrap: pretty`; the defaults have zero specificity,
 * so any text-wrap you declare wins.
 *
 * Other attributes:
 *   size    — letter | a4 | legal (default letter). Flowing documents:
 *           preview proportion only — it does NOT pin their printed
 *           paper (the print dialog's paper governs); leave it alone
 *           there. Explicitly paginated documents: it sets the page box
 *           the cards and the pinned @page share (the export dialog's
 *           choice overrides both at print) — set size="a4" for a
 *           clearly metric user. Scaled-fit: names the sheet the fit is
 *           computed against, same a4-for-metric-users advice.
 *   content-width / content-height — the design's own fixed dimensions
 *           (CSS lengths), for scaling a fixed-size design ONTO the
 *           named sheet: content lays out at exactly this size, and the
 *           component scales it to fit that sheet's printable area
 *           (centered horizontally, top-aligned; the export dialog
 *           re-fits to the user's actual paper choice where available).
 *           Both must be set; they do not change the page box. For pages
 *           WITHOUT running header/footer slots.
 *   margin  — printable inset on every page of a FLOWING document
 *           (default 0.75in); margin="0" makes pages full-bleed.
 *           Explicitly paginated pages are always full-bleed.
 *
 * Running header/footer (flowing documents only): give an element
 * `slot="header"` or `slot="footer"` and it repeats on every printed
 * page via `position: fixed`. To keep body text from sliding under it,
 * the component prints inside a single-cell table whose <thead>/<tfoot>
 * are spacers sized to the header/footer height — browsers repeat
 * thead/tfoot on every page, so each sheet's content starts below the
 * header and ends above the footer. On screen the header/footer render
 * once at the top/bottom of the sheet.
 *
 * At print the component injects `@page { margin: 0 }` (which leaves
 * Chrome no margin box to draw its date/URL/page-count header in) and
 * moves the visual margin onto the sheet's own padding. It also marks
 * the document as owning its print CSS (a
 * `meta[name="omelette-owns-print"]` it injects at runtime), so the
 * PDF export never injects page-geometry CSS of its own on top.
 *
 * Print best practices for the content you author:
 * - Multi-column text: use CSS columns (`column-count` +
 *   `column-gap`), never side-by-side flex/grid columns — only real
 *   CSS columns flow and break across pages. `column-span: all` lets
 *   a heading span the columns; `hyphens: auto` (needs `lang` on
 *   the html element) keeps narrow columns readable.
 * - Page breaks in flowing documents: `break-before: page` on an
 *   element that must start a new page (a chapter, an appendix). Add
 *   your own kept-together blocks (callouts, stat tiles, cards) to a
 *   `break-inside: avoid` rule, and keep each one shorter than a page.
 * - Extend `orphans: 3; widows: 3` to any custom text blocks you add
 *   (p and li are covered by default).
 * - Give long tables a <thead> — browsers repeat it on every printed
 *   page.
 * - No `position: fixed`/`sticky` and no viewport units in content:
 *   fixed elements stamp every printed page (running headers/footers go
 *   in the component's slots) and `100vh` mis-sizes at print.
 *
 * Author content as static HTML so the user can click-to-edit any text
 * directly. Do not set width/padding/background on the document body —
 * the component owns the sheet box.
 */
/* END USAGE */

(() => {
  const PAPER = {
    letter: ['8.5in', '11in'],
    a4: ['210mm', '297mm'],
    legal: ['8.5in', '14in']
  };
  const CSS_LENGTH = /^\d+(\.\d+)?(px|in|mm|cm|pt|pc)$/;
  // Unitless "0" is a valid CSS length and the natural way to write
  // margin="0"; normalise it to 0px so max()/calc() (which reject a bare
  // number) keep working.
  const safeLen = (v, fb) => {
    v = (v || '').trim();
    return v === '0' ? '0px' : CSS_LENGTH.test(v) ? v : fb;
  };
  // WebKit (Safari and every iOS browser shell) never repeats a table's
  // thead/tfoot on printed pages (WebKit bug 17205), so the spacer-borne
  // vertical margins of a FLOWING document reach only the first page
  // there. Engine check, not browser check: vendor is 'Apple Computer,
  // Inc.' exactly for WebKit and 'Google Inc.' for Blink.
  const WK_PRINT = /apple/i.test(navigator.vendor || '');
  // CSS length → px number (CSS absolute units are exact: 1in = 96px).
  // Returns NaN for anything safeLen would reject — callers gate on it.
  const PX_PER = {
    px: 1,
    in: 96,
    mm: 96 / 25.4,
    cm: 96 / 2.54,
    pt: 96 / 72,
    pc: 16
  };
  const toPx = v => {
    const m = /^(\d+(?:\.\d+)?)(px|in|mm|cm|pt|pc)$/.exec((v || '').trim());
    return m ? parseFloat(m[1]) * PX_PER[m[2]] : NaN;
  };
  const stylesheet = `
    :host {
      position: relative;
      display: block;
      /* When the viewport is narrower than the page, grow to wrap the
       * sheet (plus this padding) instead of staying viewport-width, so
       * the desk background and right margin reach the sheet's far edge
       * in the horizontal scroll. */
      min-width: max-content;
      min-height: 100vh;
      background: #f5f5f4;
      padding: 48px 24px;
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      --doc-page-w: 8.5in;
      --doc-page-h: 11in;
      --doc-page-margin: 0.75in;
      --doc-hdr-h: 0px;
      --doc-ftr-h: 0px;
      --doc-hdr-pad: 0px;
      --doc-ftr-pad: 0px;
    }
    .sheet {
      width: var(--doc-page-w);
      margin: 0 auto;
      background: #fff;
      box-shadow: 0 2px 10px rgba(20, 20, 19, 0.12);
      border-radius: 7px;
      box-sizing: border-box;
      padding: var(--doc-page-margin);
    }
    .frame { width: 100%; border-collapse: collapse; }
    /* Scaled-fit mode (content-width/content-height): the inner .fit box
     * lays the content out at its authored fixed size and scales it onto
     * the printable area; .fit-box reserves the scaled footprint in flow
     * (transforms don't affect layout) and centers it. Without the mode,
     * both divs are unstyled block pass-throughs. */
    /* Explicit pagination: direct .page children are the pages. The sheet
     * becomes a transparent stack and each page carries the card look on
     * screen; at print each page is exactly one full-bleed sheet. The
     * ::slotted defaults are deliberately weak (document CSS wins), so
     * authored page styling can override any of this. */
    .sheet.paginated {
      background: transparent;
      box-shadow: none;
      border-radius: 0;
      padding: 0;
    }
    .paginated ::slotted(.page) {
      position: relative;
      display: block;
      width: 100%;
      aspect-ratio: var(--doc-page-ar);
      container-type: size;
      overflow: hidden;
      box-sizing: border-box;
      background: #fff;
      border-radius: 7px;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
      break-inside: avoid;
    }
    .paginated ::slotted(.page:not(:first-child)) { margin-top: 1rem; }
    @media print {
      .sheet.paginated { padding: 0; }
      /* The flowing-document vertical inset lives on the repeating
       * thead/tfoot spacers, not the sheet padding — they must go too,
       * or each full-sheet .page is pushed ~margin down and spills onto
       * a second sheet. Paginated pages are full-bleed by definition
       * (content owns its insets). */
      .sheet.paginated .hdr-space,
      .sheet.paginated .ftr-space { height: 0; }
      .paginated ::slotted(.page) {
        border-radius: 0 !important;
        box-shadow: none !important;
        margin: 0 !important;
        /* Physical page-box sizing, no viewport units: Safari resolves
         * 100vh against the window, not the page box, so a vh-sized card
         * paginates wrong there. --doc-page-w/h are the named size by
         * default and are overridden to the user's chosen paper by the
         * export path, so every card is exactly one sheet either way.
         * Width + height (same source values as @page size) rather than
         * width + aspect-ratio: the ratio is a 6-decimal rounding of the
         * same division, and a few millionths of overflow would spill a
         * blank sheet after every page. The screen-only aspect-ratio
         * (preview proportions) must not leak into print. cqh typography
         * tracks the same box.
         *
         * Every declaration is !important: per CSS Scoping, unimportant
         * shadow ::slotted rules LOSE to the document context, so a page
         * section's authored inline style would silently beat this print
         * geometry. A model-authored height:100% did exactly that — the
         * percentage resolves as auto in the all-auto print ancestry, the
         * base rule's size containment turns auto into ZERO, and
         * overflow:hidden then paints nothing: a blank PDF with perfect
         * page boxes. At print the component's geometry is the design's
         * whole contract, so it must win over any authored sizing. */
        aspect-ratio: auto !important;
        width: var(--doc-page-w) !important;
        height: var(--doc-page-h) !important;
        overflow: hidden !important;
      }
      .paginated ::slotted(.page:not(:first-child)) {
        break-before: page !important;
        margin-top: 0 !important;
      }
    }
    .fit-mode .fit-box {
      width: calc(var(--doc-fit-w) * var(--doc-fit-scale));
      height: calc(var(--doc-fit-h) * var(--doc-fit-scale));
      margin: 0 auto;
      break-inside: avoid;
    }
    /* Monolithic at print: Blink slices a transform-scaled child at
     * fragmentainer boundaries mapped in UNSCALED layout coordinates
     * (transforms are paint-time), so the .fit box (authored size, e.g.
     * 1400x990) gets cut at the page's free block space and spills onto
     * a second sheet even though its SCALED footprint fits the page by
     * construction. overflow:hidden makes .fit-box a scroll container —
     * monolithic under fragmentation (css-break-3) — so the scaled
     * content prints atomically on one sheet. No clipping for content
     * within the authored box: .fit-box is calc-sized to exactly the
     * scaled footprint. (Content that bleeds past content-width/height
     * is clipped at the footprint — fit mode's contract; it previously
     * painted beyond it at print.) Print-only, so the screen rendering
     * keeps visible overflow for editor affordances.
     * The export path injects the same rule into frozen copies
     * (print-eval.ts om-print-fit-contain). The .fit-mode scope is
     * load-bearing: .fit-box wraps slotted content in EVERY mode, and an
     * unscoped overflow:hidden would make whole flowing documents
     * monolithic (one truncated sheet). overflow:hidden, never clip —
     * clip is not a scroll container, so not monolithic. */
    @media print {
      .fit-mode .fit-box { overflow: hidden; }
    }
    .fit-mode .fit {
      width: var(--doc-fit-w);
      height: var(--doc-fit-h);
      transform: scale(var(--doc-fit-scale));
      transform-origin: top left;
    }
    .frame td, .frame th { padding: 0; text-align: left; font-weight: inherit; }
    .hdr-space { height: var(--doc-hdr-h); }
    .ftr-space { height: var(--doc-ftr-h); }
    ::slotted([slot="header"]),
    ::slotted([slot="footer"]) { display: block; box-sizing: border-box; }
    @media print {
      :host { background: none; padding: 0; min-width: 0; min-height: 0; }
      .sheet {
        width: auto; margin: 0; box-shadow: none; border-radius: 0;
        padding: 0 var(--doc-page-margin);
      }
      /* The thead/tfoot spacers repeat on every page, so they carry the
       * vertical page margin (which the sheet's own padding cannot, since
       * that padding is consumed once on the first/last page). The running
       * header/footer are fixed inside that band. */
      /* The 0.35in is breathing room between a running header/footer and
       * the body; without one the spacer is exactly the page margin, so a
       * margin="0" full-bleed document gets truly full-bleed pages. */
      .hdr-space { height: max(var(--doc-page-margin), calc(var(--doc-hdr-h) + var(--doc-hdr-pad))); }
      .ftr-space { height: max(var(--doc-page-margin), calc(var(--doc-ftr-h) + var(--doc-ftr-pad))); }
      /* WebKit flowing documents: @page carries the vertical margin (see
       * _syncPrintPageRule), so the spacers keep only whatever a running
       * header/footer needs BEYOND it — page 1 would otherwise double its
       * top inset. Paginated sheets already zero their spacers above. */
      .sheet.wk-print:not(.paginated) .hdr-space { height: max(0px, calc(max(var(--doc-page-margin), calc(var(--doc-hdr-h) + var(--doc-hdr-pad))) - var(--doc-page-margin))); }
      .sheet.wk-print:not(.paginated) .ftr-space { height: max(0px, calc(max(var(--doc-page-margin), calc(var(--doc-ftr-h) + var(--doc-ftr-pad))) - var(--doc-page-margin))); }
      ::slotted([slot="header"]) {
        position: fixed; top: 0; left: 0; right: 0; margin: 0;
        padding: calc(var(--doc-page-margin) * 0.45) var(--doc-page-margin) 0;
      }
      ::slotted([slot="footer"]) {
        position: fixed; bottom: 0; left: 0; right: 0; margin: 0;
        padding: 0 var(--doc-page-margin) calc(var(--doc-page-margin) * 0.45);
      }
    }
  `;
  class DocPage extends HTMLElement {
    static get observedAttributes() {
      return ['size', 'width', 'height', 'margin', 'orientation', 'content-width', 'content-height'];
    }
    constructor() {
      super();
      this._root = this.attachShadow({
        mode: 'open'
      });
      this._mo = typeof MutationObserver === 'function' ? new MutationObserver(() => this._scheduleMeasure()) : null;
    }

    /** The named paper's [w, h], swapped when orientation="landscape".
     *  Only the named size swaps — explicit width/height are exact values
     *  the author already oriented. */
    _paperSize() {
      const named = PAPER[(this.getAttribute('size') || '').toLowerCase()] || PAPER.letter;
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      return landscape ? [named[1], named[0]] : named;
    }
    get pageWidth() {
      return safeLen(this.getAttribute('width'), this._paperSize()[0]);
    }
    get pageHeight() {
      return safeLen(this.getAttribute('height'), this._paperSize()[1]);
    }
    get pageMargin() {
      return safeLen(this.getAttribute('margin'), '0.75in');
    }

    /** Scaled-fit mode's content box [w, h] as CSS lengths, or null when
     *  the mode is off (either attribute missing/invalid/zero — a partial
     *  declaration falls back to normal flow rather than guessing). */
    _contentFit() {
      const w = safeLen(this.getAttribute('content-width'), null);
      const h = safeLen(this.getAttribute('content-height'), null);
      if (!w || !h) return null;
      const wPx = toPx(w),
        hPx = toPx(h);
      return wPx > 0 && hPx > 0 ? [w, h, wPx, hPx] : null;
    }
    connectedCallback() {
      if (!this._sheet) this._render();
      this._syncSize();
      this._syncPrintPageRule();
      this._ensureTextWrapDefaults();
      this._ensureOwnsPrintMeta();
      this._syncFixedSizeMeta();
      this._syncPrintSizingMeta();
      if (this._mo) this._mo.observe(this, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true
      });
      this._onResize = () => this._scheduleMeasure();
      window.addEventListener('resize', this._onResize);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(() => this._scheduleMeasure());
      }
      this._scheduleMeasure();
    }
    disconnectedCallback() {
      window.removeEventListener('resize', this._onResize);
      if (this._mo) this._mo.disconnect();
      if (this._raf) {
        cancelAnimationFrame(this._raf);
        this._raf = null;
      }
      // Drop the head rules when the last doc-page leaves, so a deleted
      // document's @page geometry and text-wrap defaults can't apply to
      // whatever replaces it.
      const survivor = document.querySelector('doc-page');
      if (!survivor) {
        ['doc-page-print', 'doc-page-text-wrap', 'doc-page-owns-print', 'doc-page-fixed-size', 'doc-page-print-sizing'].forEach(id => {
          const tag = document.getElementById(id);
          if (tag) tag.remove();
        });
        // A live deck-stage deferred its own print-sizing meta to ours —
        // hand the page-global meta over so the deck isn't left unmarked.
        const deck = document.querySelector('deck-stage');
        if (deck && typeof deck._ensurePrintSizingMeta === 'function') {
          deck._ensurePrintSizingMeta();
        }
      } else {
        // A departed owner hands each page-global meta to whatever
        // doc-page remains (or it's removed).
        if (typeof survivor._syncFixedSizeMeta === 'function') {
          survivor._syncFixedSizeMeta();
        }
        if (typeof survivor._syncPrintSizingMeta === 'function') {
          survivor._syncPrintSizingMeta();
        }
      }
    }
    attributeChangedCallback() {
      if (!this._sheet) return;
      this._syncSize();
      this._syncPrintPageRule();
      this._syncFixedSizeMeta();
      this._syncPrintSizingMeta();
      this._scheduleMeasure();
    }
    _render() {
      this._root.innerHTML = `
        <style>${stylesheet}</style>
        <style id="vars"></style>
        <div class="sheet" data-screen-label="Document">
          <table class="frame" role="presentation">
            <thead><tr><th><div class="hdr-space"><slot name="header"></slot></div></th></tr></thead>
            <tbody><tr><td class="body"><div class="fit-box"><div class="fit"><slot></slot></div></div></td></tr></tbody>
            <tfoot><tr><td><div class="ftr-space"><slot name="footer"></slot></div></td></tr></tfoot>
          </table>
        </div>`;
      this._sheet = this._root.querySelector('.sheet');
      this._vars = this._root.getElementById('vars');
    }

    /** Runtime sizing lives in a shadow <style> :host rule, never on the
     *  light-DOM host element, so serialize-persist can't write it back. */
    _syncSize(hdrH, ftrH) {
      // Scaled-fit mode: content at its authored size, scaled onto the
      // printable area (page minus margins on both axes). The factor is a
      // plain number var so calc(length * number) stays valid; 4 decimals
      // keeps the shadow style stable across re-measures. Upscaling is
      // allowed — print transforms are vector, so text and CSS stay crisp
      // (raster images soften, which the catalog bullet warns about).
      const fit = this._contentFit();
      let fitVars = '';
      if (fit) {
        const marginPx = toPx(this.pageMargin) || 0;
        const availW = toPx(this.pageWidth) - 2 * marginPx;
        const availH = toPx(this.pageHeight) - 2 * marginPx;
        const scale = Math.min(availW / fit[2], availH / fit[3]);
        if (scale > 0 && Number.isFinite(scale)) {
          fitVars = '--doc-fit-w:' + fit[0] + ';' + '--doc-fit-h:' + fit[1] + ';' + '--doc-fit-scale:' + scale.toFixed(4) + ';';
        }
      }
      this._sheet.classList.toggle('fit-mode', !!fitVars);
      // Numeric w/h ratio for the paginated page cards' aspect-ratio —
      // aspect-ratio takes a number, not a length ratio, so compute it
      // here (CSS length division isn't portable). 6 decimals keeps the
      // shadow style stable across re-syncs.
      const arW = toPx(this.pageWidth);
      const arH = toPx(this.pageHeight);
      const ar = arW > 0 && arH > 0 ? (arW / arH).toFixed(6) : '0.772727';
      this._vars.textContent = ':host{' + fitVars + '--doc-page-ar:' + ar + ';' + '--doc-page-w:' + this.pageWidth + ';' + '--doc-page-h:' + this.pageHeight + ';' + '--doc-page-margin:' + this.pageMargin + ';' + '--doc-hdr-h:' + (hdrH || 0) + 'px;' + '--doc-ftr-h:' + (ftrH || 0) + 'px;' + '--doc-hdr-pad:' + (hdrH ? '0.35in' : '0px') + ';' + '--doc-ftr-pad:' + (ftrH ? '0.35in' : '0px') + '}';
    }

    /** @page is a no-op inside shadow DOM, so the rule lives in <head>.
     *  Re-appended on every sync so it stays last in source order — the
     *  @page cascade is source-order per descriptor, so this rule wins
     *  over any other @page rule in the document.
     *
     *  The @page SIZE is pinned where the page box IS part of the design:
     *  explicit-fixed-size mode (width + height authored), scaled-fit
     *  mode (the named sheet the fit targets), and explicit pagination
     *  (the named size the cards share — so card and sheet agree on
     *  every print path, and the export path's chosen paper overrides
     *  BOTH with one later rule). For FLOWING documents no paper size is
     *  emitted at all — the true size comes from the user's preference,
     *  injected by the export path or chosen in the print dialog — so a
     *  flowing document never fights the paper it lands on.
     *  margin: 0 is emitted in every mode: it leaves Chrome no margin box
     *  to draw its date/URL/page-count header in, and the visual margin
     *  lives on the sheet's own padding. */
    _syncPrintPageRule() {
      const id = 'doc-page-print';
      let tag = document.getElementById(id);
      if (!tag) {
        tag = document.createElement('style');
        tag.id = id;
      }
      document.head.appendChild(tag);
      // Three print-geometry regimes:
      // - true-size: the page IS the design — pin its exact size.
      // - scaled-fit (content-width/height): the fit factor is computed
      //   against the NAMED paper's printable area, so that paper must
      //   stay pinned or the scaled content overflows a smaller sheet
      //   (the export path re-fits and re-pins at print time on top).
      // - default modes: no paper size — but landscape still needs the
      //   paper-agnostic 'size: landscape' keyword, because the size
      //   descriptor is what carries orientation; without it a landscape
      //   document prints portrait whenever nothing injects a size.
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      // Explicit pagination pins the page box to the SAME values that
      // size the cards (the named size by default, the export path's
      // chosen paper when its later rule overrides both) — card and
      // sheet agree on every print path, and a mismatched real paper
      // shrinks-to-fit in the dialog instead of clipping a Letter card
      // on A4. Declared before the paginated read below so both derive
      // from one check.
      const paginatedNow = this.querySelector(':scope > .page') !== null;
      const sizeDescriptor = this._trueSizePx() ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : this._contentFit() ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : paginatedNow ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : landscape ? 'size: landscape; ' : '';
      // WebKit never repeats the thead/tfoot spacers that carry a flowing
      // document's vertical page margins (see WK_PRINT above), so pages
      // after the first print edge-to-edge there. Carry the VERTICAL
      // margins on @page for WebKit instead, and the shadow print CSS
      // trims the first-page spacers by the same amount (.sheet.wk-print
      // rules). Horizontal inset stays on the sheet's own padding in
      // every engine. Blink keeps margin: 0 (a nonzero margin there
      // re-opens the box Chrome draws its header furniture in). One cost,
      // learned in testing: Safari's own date/URL headers are a USER
      // dialog setting ("Print headers and footers") that renders in the
      // margin area when room exists — margin: 0 only suppressed it by
      // leaving no room, and no CSS controls it. The export dialog's
      // Safari guide teaches turning the setting off for flowing
      // documents. Explicitly paginated and fixed-size documents keep
      // margin: 0 everywhere: their pages ARE the sheet.
      const wkFlowing = WK_PRINT && !paginatedNow && !this._trueSizePx() && !this._contentFit();
      const marginDescriptor = wkFlowing ? 'margin: ' + this.pageMargin + ' 0; ' : 'margin: 0; ';
      // Shadow-internal marker (never serialized), kept in lockstep with
      // the @page decision above: the print CSS trims the first-page
      // spacers ONLY while @page actually carries the margins — a
      // true-size or scaled-fit sheet keeps margin: 0 and must keep its
      // spacers too. Re-synced here so attribute changes and pagination
      // flips move both together.
      if (this._sheet) this._sheet.classList.toggle('wk-print', wkFlowing);
      tag.textContent = '@page { ' + sizeDescriptor + marginDescriptor + '} ' + '@media print { html, body { margin: 0 !important; padding: 0 !important; background: none !important; height: auto !important; overflow: visible !important; } ' + 'h1,h2,h3,h4,h5,h6 { break-after: avoid; } ' + 'figure,pre,blockquote,img,svg,tr { break-inside: avoid; } ' + 'p,li { orphans: 3; widows: 3; } ' + '* { -webkit-print-color-adjust: exact; print-color-adjust: exact; ' + 'backdrop-filter: none !important; -webkit-backdrop-filter: none !important; } ' + '*, *::before, *::after { animation-delay: -99s !important; animation-duration: .001s !important; ' + 'animation-iteration-count: 1 !important; animation-fill-mode: both !important; ' + 'animation-play-state: running !important; transition-duration: 0s !important; } }';
    }

    /** Typographic defaults for document text: balance headings, avoid
     *  widowed/orphaned words in body copy (browsers without text-wrap
     *  support drop the declarations). Zero-specificity via :where() so
     *  any text-wrap authored on those elements wins; document-level so the
     *  rules reach the slotted (light DOM) content — shadow styles can't.
     *  data-omelette-injected marks the tag for the host editor to strip
     *  at serialize, so it is never written back as authored source. */
    _ensureTextWrapDefaults() {
      if (document.getElementById('doc-page-text-wrap')) return;
      const tag = document.createElement('style');
      tag.id = 'doc-page-text-wrap';
      tag.setAttribute('data-omelette-injected', '');
      tag.textContent = ':where(h1,h2,h3,h4,h5,h6){text-wrap:balance}' + ':where(p,li,blockquote,figcaption){text-wrap:pretty}';
      document.head.appendChild(tag);
    }

    /** Declares that this document owns its print CSS. The instant-PDF
     *  export checks for the meta by NAME PRESENCE alone (content is
     *  ignored) and skips its automatic print-CSS injections, so the
     *  component's @page geometry is never overridden by a heuristic.
     *  data-omelette-injected keeps it out of serialized source. */
    _ensureOwnsPrintMeta() {
      if (document.getElementById('doc-page-owns-print')) return;
      const tag = document.createElement('meta');
      tag.id = 'doc-page-owns-print';
      tag.name = 'omelette-owns-print';
      tag.content = 'true';
      tag.setAttribute('data-omelette-injected', '');
      document.head.appendChild(tag);
    }

    /** This page's valid true-size page box (explicit width AND height)
     *  as [w, h] px ints, or null when the mode is off. */
    _trueSizePx() {
      if (!safeLen(this.getAttribute('width'), null) || !safeLen(this.getAttribute('height'), null)) return null;
      const w = Math.round(toPx(this.pageWidth));
      const h = Math.round(toPx(this.pageHeight));
      return w > 0 && h > 0 ? [w, h] : null;
    }

    /** True-size pages (explicit width AND height) also declare the page
     *  box as the preview size: the in-app preview reads
     *  meta[name="omelette-fixed-size"] (content "W,H" in px ints) and
     *  scales the sheet into view — without it an 18in poster previews at
     *  true size with scrollbars. Never overrides an author-set meta
     *  (only the component's own id is managed). The meta is page-global
     *  while doc-page instances are not, so every sync recomputes the
     *  page-wide owner — the first connected true-size doc-page — and a
     *  non-true-size sibling's sync can never delete the owner's meta.
     *  Removed when no true-size page remains (the owner's disconnect
     *  re-syncs via any survivor) or when an author-set meta exists. */
    _syncFixedSizeMeta() {
      const id = 'doc-page-fixed-size';
      const own = document.getElementById(id);
      const authored = document.querySelector('meta[name="omelette-fixed-size"]:not([data-omelette-injected])');
      // The page-wide owner, not this instance: an upgraded true-size page
      // anywhere in the document keeps the meta alive and sized.
      let box = null;
      for (const el of document.querySelectorAll('doc-page')) {
        box = typeof el._trueSizePx === 'function' ? el._trueSizePx() : null;
        if (box) break;
      }
      if (!box || authored) {
        if (own) own.remove();
        return;
      }
      const tag = own || document.createElement('meta');
      tag.id = id;
      tag.name = 'omelette-fixed-size';
      tag.content = box[0] + ',' + box[1];
      tag.setAttribute('data-omelette-injected', '');
      if (!own) document.head.appendChild(tag);
    }

    /** This page's print-sizing mode: 'fixed' when an explicit width AND
     *  height are authored (the page is the design's own size), else the
     *  default paper in the authored orientation. */
    _printSizingMode() {
      if (this._trueSizePx()) return 'fixed';
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      return landscape ? 'default-landscape' : 'default-portrait';
    }

    /** Announces the print-sizing mode to the host app:
     *  meta[name="omelette-print-sizing"] with content 'default-portrait',
     *  'default-landscape', or 'fixed' (fixed pages also carry the
     *  omelette-fixed-size meta with the page box in px). The export path
     *  probes it to decide what true paper size to inject at print time —
     *  in the default modes the component emits no paper size of its own.
     *  Same page-global ownership rules as the fixed-size meta above:
     *  first connected doc-page owns it, an authored meta is never
     *  overridden, removed when no doc-page remains. */
    _syncPrintSizingMeta() {
      const id = 'doc-page-print-sizing';
      const own = document.getElementById(id);
      const authored = document.querySelector('meta[name="omelette-print-sizing"]:not([data-omelette-injected])');
      // A fixed page wins outright (mirroring the fixed-size loop above,
      // so the two metas can never contradict each other in a mixed
      // multi-page document); otherwise the first page's mode holds.
      let mode = null;
      for (const el of document.querySelectorAll('doc-page')) {
        if (typeof el._printSizingMode !== 'function') continue;
        const m = el._printSizingMode();
        if (m === 'fixed') {
          mode = m;
          break;
        }
        if (mode === null) mode = m;
      }
      if (!mode || authored) {
        if (own) own.remove();
        return;
      }
      // A deck-stage that connected first injected its own meta and
      // defers to any existing one — take it over, or the document ends
      // up with two conflicting injected metas (a doc-page page is the
      // document; the deck re-ensures its meta if every doc-page leaves).
      const deckMeta = document.getElementById('deck-stage-print-sizing');
      if (deckMeta) deckMeta.remove();
      const tag = own || document.createElement('meta');
      tag.id = id;
      tag.name = 'omelette-print-sizing';
      tag.content = mode;
      tag.setAttribute('data-omelette-injected', '');
      if (!own) document.head.appendChild(tag);
    }
    _scheduleMeasure() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = null;
        this._measure();
      });
    }

    /** Slot heights feed the print spacers (--doc-hdr-h / --doc-ftr-h), so
     *  they re-measure on content mutation, resize, and font load. The
     *  same pass detects explicit pagination (direct .page children) and
     *  toggles the sheet between the flowing-document card and the
     *  page-per-card stack — content edits can add or remove pages at any
     *  time, so this tracks the same mutations the measurement does. */
    _measure() {
      const hdr = this.querySelector(':scope > [slot="header"]');
      const ftr = this.querySelector(':scope > [slot="footer"]');
      const wasPaginated = this._sheet.classList.contains('paginated');
      this._sheet.classList.toggle('paginated', this.querySelector(':scope > .page') !== null);
      // The WebKit @page margin is flowing-only, so a pagination flip
      // must re-emit the rule (content edits can add or remove .page
      // sections at any time).
      if (this._sheet.classList.contains('paginated') !== wasPaginated) {
        this._syncPrintPageRule();
      }
      this._syncSize(hdr ? hdr.offsetHeight : 0, ftr ? ftr.offsetHeight : 0);
    }
  }
  if (!customElements.get('doc-page')) {
    customElements.define('doc-page', DocPage);
  }
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "doc-page.js", error: String((e && e.message) || e) }); }

// ui_kits/website/Features.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// SpinSci UI Kit — feature grid (2-up light cards with hover lift)
const FEATURES = [{
  icon: "calendar",
  tint: "mint",
  title: "Self-scheduling",
  body: "Patients book, reschedule, and confirm appointments without a call — written straight to your EHR."
}, {
  icon: "phone",
  tint: "violet",
  title: "Contact center assist",
  body: "A 360° patient view surfaces the right context to agents the moment a call connects."
}, {
  icon: "pill",
  tint: "mint",
  title: "Pharmacy & refills",
  body: "Refill requests, prior-auth status, and med questions resolved automatically, day or night."
}, {
  icon: "route",
  tint: "violet",
  title: "Referrals & transfers",
  body: "Route referrals and inter-facility transfers without the fax-and-phone-tag."
}];
const FeatureCard = ({
  icon,
  tint,
  title,
  body
}) => {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      background: "#fff",
      border: "1px solid var(--border-hairline)",
      borderRadius: "var(--radius-lg)",
      padding: 32,
      boxShadow: hover ? "var(--shadow-card-hover)" : "var(--shadow-card)",
      transform: hover ? "translateY(-2px)" : "none",
      transition: "transform 200ms ease, box-shadow 200ms ease"
    }
  }, /*#__PURE__*/React.createElement(IconBox, {
    name: icon,
    tint: tint
  }), /*#__PURE__*/React.createElement("h3", {
    style: {
      font: "300 28px/1.05 var(--font-display)",
      letterSpacing: "-0.9px",
      color: "var(--color-ink)",
      margin: "20px 0 10px"
    }
  }, title), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "400 15px/23px var(--font-ui)",
      color: "var(--color-text-secondary)",
      margin: 0
    }
  }, body));
};
const Features = () => /*#__PURE__*/React.createElement("section", {
  style: {
    background: "var(--color-surface)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    maxWidth: "var(--max-content)",
    margin: "0 auto",
    padding: "80px var(--gutter)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    maxWidth: 620,
    marginBottom: 48
  }
}, /*#__PURE__*/React.createElement(Eyebrow, null, "The Platform"), /*#__PURE__*/React.createElement("h2", {
  style: {
    font: "300 48px/52px var(--font-display)",
    letterSpacing: "-1.9px",
    color: "var(--color-ink)",
    margin: "20px 0 0",
    textWrap: "balance"
  }
}, "One access layer across every patient touchpoint.")), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 24
  }
}, FEATURES.map(f => /*#__PURE__*/React.createElement(FeatureCard, _extends({
  key: f.title
}, f))))));
window.Features = Features;
Object.assign(__ds_scope, { Features });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Features.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Hero.jsx
try { (() => {
// SpinSci UI Kit — Hero with ambient mint wash + floating live-call card
const Hero = ({
  onDemo
}) => /*#__PURE__*/React.createElement("section", {
  style: {
    position: "relative",
    overflow: "hidden",
    background: "var(--color-white)"
  }
}, /*#__PURE__*/React.createElement("div", {
  className: "kit-herowash",
  style: {
    position: "absolute",
    inset: 0,
    background: "radial-gradient(110% 80% at 88% -10%, rgba(92,224,176,0.20) 0%, rgba(119,89,217,0.06) 40%, rgba(255,255,255,0) 62%)",
    pointerEvents: "none"
  }
}), /*#__PURE__*/React.createElement("div", {
  style: {
    position: "relative",
    maxWidth: "var(--max-content)",
    margin: "0 auto",
    padding: "96px var(--gutter) 80px",
    display: "grid",
    gridTemplateColumns: "1.05fr 0.95fr",
    gap: 56,
    alignItems: "center"
  }
}, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "Patient Access, Automated"), /*#__PURE__*/React.createElement("h1", {
  style: {
    font: "300 64px/68px var(--font-display)",
    letterSpacing: "-2.6px",
    color: "var(--color-ink)",
    margin: "24px 0 0",
    textWrap: "balance"
  }
}, "Remove every point of friction in ", /*#__PURE__*/React.createElement("span", {
  className: "ds-gradient-text"
}, "patient access"), "."), /*#__PURE__*/React.createElement("p", {
  style: {
    font: "400 18px/27px var(--font-ui)",
    color: "var(--color-text-secondary)",
    margin: "22px 0 0",
    maxWidth: 480
  }
}, "SpinSci agents resolve scheduling, billing, and pharmacy requests across your existing EHR \u2014 so your teams focus on care, not call queues."), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    gap: 12,
    marginTop: 32
  }
}, /*#__PURE__*/React.createElement(Button, {
  variant: "primary",
  size: "lg",
  icon: "arrow",
  onClick: onDemo
}, "Book a demo"), /*#__PURE__*/React.createElement(Button, {
  variant: "ghost",
  size: "lg",
  icon: "arrow"
}, "See the platform")), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    gap: 28,
    marginTop: 40
  }
}, [["165", "Health systems"], ["400M+", "Interactions"], ["60M", "Patients reached"]].map(([n, l]) => /*#__PURE__*/React.createElement("div", {
  key: l
}, /*#__PURE__*/React.createElement("div", {
  style: {
    font: "300 34px/1 var(--font-display)",
    letterSpacing: "-1px",
    color: "var(--color-ink)"
  }
}, n), /*#__PURE__*/React.createElement("div", {
  style: {
    font: "700 11px/1.4 var(--font-ui)",
    letterSpacing: "0.6px",
    textTransform: "uppercase",
    color: "var(--color-text-secondary)",
    marginTop: 6
  }
}, l))))), /*#__PURE__*/React.createElement(HeroCard, null)));
const HeroCard = () => {
  const msgs = [{
    who: "agent",
    text: "Hi Maria — I can help you reschedule your cardiology visit. Does Thursday at 9:40 AM work?"
  }, {
    who: "patient",
    text: "Yes, that's perfect."
  }, {
    who: "agent",
    text: "Done. You're confirmed for Thu, Jun 5 · 9:40 AM. A reminder will text you the day before."
  }];
  const [shown, setShown] = React.useState(0);
  React.useEffect(() => {
    if (shown >= msgs.length) return;
    const t = setTimeout(() => setShown(s => s + 1), shown === 0 ? 400 : 900);
    return () => clearTimeout(t);
  }, [shown]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "#fff",
      border: "1px solid var(--border-hairline)",
      borderRadius: "var(--radius-xl)",
      boxShadow: "var(--shadow-card)",
      padding: 24
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      paddingBottom: 16,
      borderBottom: "1px solid var(--border-faint)"
    }
  }, /*#__PURE__*/React.createElement(IconBox, {
    name: "sparkle",
    tint: "violet",
    size: 38,
    icon: 20
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "600 14px/1 var(--font-ui)",
      color: "var(--color-ink)"
    }
  }, "SpinSci Scheduling Agent"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      marginTop: 5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: "var(--color-mint)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "400 12px/1 var(--font-ui)",
      color: "var(--color-text-secondary)"
    }
  }, "Live \xB7 resolving in 0:14")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 10,
      padding: "18px 0 4px",
      minHeight: 230
    }
  }, msgs.slice(0, shown).map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "kit-bubble",
    style: {
      alignSelf: m.who === "patient" ? "flex-end" : "flex-start",
      maxWidth: "82%",
      background: m.who === "patient" ? "var(--color-navy)" : "var(--color-surface)",
      color: m.who === "patient" ? "#fff" : "var(--color-ink)",
      border: m.who === "patient" ? "none" : "1px solid var(--border-faint)",
      borderRadius: m.who === "patient" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
      padding: "12px 14px",
      font: "400 13px/19px var(--font-ui)"
    }
  }, m.text))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginTop: 8,
      paddingTop: 14,
      borderTop: "1px solid var(--border-faint)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      font: "400 11px/1 var(--font-ui)",
      color: "var(--color-text-secondary)"
    }
  }, "Synced to"), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "600 11px/1 var(--font-ui)",
      color: "var(--color-teal)",
      background: "var(--color-success-bg)",
      border: "1px solid var(--border-teal)",
      borderRadius: 6,
      padding: "5px 9px"
    }
  }, "EHR \xB7 Appointments")));
};
window.Hero = Hero;
Object.assign(__ds_scope, { Hero });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Hero.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Nav.jsx
try { (() => {
// SpinSci UI Kit — top navigation (transparent over hero, frosted on scroll)
const Nav = ({
  onDemo
}) => {
  const [scrolled, setScrolled] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    const root = document.querySelector("#kit-scroll") || window;
    const onScroll = () => {
      const y = root === window ? window.scrollY : root.scrollTop;
      setScrolled(y > 24);
    };
    root.addEventListener("scroll", onScroll);
    return () => root.removeEventListener("scroll", onScroll);
  }, []);
  const links = ["Platform", "Solutions", "Customers", "Resources", "Company"];
  return /*#__PURE__*/React.createElement("header", {
    style: {
      position: "sticky",
      top: 0,
      zIndex: 50,
      background: scrolled ? "rgba(255,255,255,0.95)" : "transparent",
      backdropFilter: scrolled ? "saturate(180%) blur(12px)" : "none",
      borderBottom: scrolled ? "1px solid var(--border-faint)" : "1px solid transparent",
      transition: "background 250ms ease, border-color 250ms ease"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--max-content)",
      margin: "0 auto",
      padding: "16px var(--gutter)",
      display: "flex",
      alignItems: "center",
      gap: 24
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/spinsci-logo.svg",
    alt: "SpinSci",
    style: {
      height: 28
    }
  }), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      gap: 4,
      marginLeft: 16
    },
    className: "kit-navlinks"
  }, links.map(l => /*#__PURE__*/React.createElement("a", {
    key: l,
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 14,
      fontWeight: 500,
      color: "var(--color-ink)",
      textDecoration: "none",
      padding: "10px 14px",
      borderRadius: 6,
      transition: "background 150ms ease"
    },
    onMouseEnter: e => e.currentTarget.style.background = "rgba(9,19,34,0.05)",
    onMouseLeave: e => e.currentTarget.style.background = "transparent"
  }, l))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 14,
      fontWeight: 600,
      color: "var(--color-ink)",
      textDecoration: "none",
      whiteSpace: "nowrap"
    },
    className: "kit-signin"
  }, "Sign in"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    icon: "arrow",
    onClick: onDemo
  }, "Book a demo"))));
};
window.Nav = Nav;
Object.assign(__ds_scope, { Nav });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Nav.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/PlatformDark.jsx
try { (() => {
// SpinSci UI Kit — dark platform section with tabbed agents (navy→teal gradient)
const AGENTS = [{
  key: "Scheduling",
  icon: "calendar",
  line: "Books, reschedules, and confirms across service lines.",
  points: ["Real-time EHR slot lookup", "Multi-visit coordination", "Automated reminders & confirmations"]
}, {
  key: "Billing",
  icon: "bolt",
  line: "Resolves balance, estimate, and payment questions.",
  points: ["Itemized balance explanations", "Pay-by-text links", "Financial-assistance routing"]
}, {
  key: "Pharmacy",
  icon: "pill",
  line: "Handles refills, status, and medication questions.",
  points: ["Refill request intake", "Prior-auth status checks", "Pharmacy handoff when needed"]
}, {
  key: "Referrals",
  icon: "route",
  line: "Moves referrals and transfers without the phone tag.",
  points: ["Specialist matching", "Inter-facility transfer intake", "Status tracking end-to-end"]
}];
const PlatformDark = () => {
  const [active, setActive] = React.useState(0);
  const a = AGENTS[active];
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--gradient-platform-bg)",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--max-content)",
      margin: "0 auto",
      padding: "80px var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 640,
      marginBottom: 44
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    onDark: true
  }, "AI Agents"), /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "300 48px/52px var(--font-display)",
      letterSpacing: "-1.9px",
      color: "#fff",
      margin: "20px 0 0",
      textWrap: "balance"
    }
  }, "Purpose-built agents for every access workflow.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      flexWrap: "wrap",
      marginBottom: 28
    }
  }, AGENTS.map((ag, i) => /*#__PURE__*/React.createElement("button", {
    key: ag.key,
    onClick: () => setActive(i),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 9,
      cursor: "pointer",
      borderRadius: "var(--radius-pill)",
      padding: "10px 18px",
      font: "600 14px/1 var(--font-ui)",
      background: i === active ? "#fff" : "rgba(255,255,255,0.06)",
      color: i === active ? "var(--color-ink)" : "rgba(255,255,255,0.75)",
      border: `1px solid ${i === active ? "#fff" : "rgba(255,255,255,0.16)"}`,
      transition: "all 180ms ease"
    }
  }, /*#__PURE__*/React.createElement(SpinIcon, {
    name: ag.icon,
    size: 16,
    strokeWidth: 2,
    color: i === active ? "var(--color-teal)" : "var(--color-mint)"
  }), ag.key))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 24,
      alignItems: "stretch"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "rgba(255,255,255,0.05)",
      border: "1px solid var(--border-on-dark)",
      borderRadius: "var(--radius-xl)",
      padding: 36
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      font: "300 32px/1.05 var(--font-display)",
      letterSpacing: "-1px",
      color: "#fff",
      margin: "0 0 12px"
    }
  }, a.key, " agent"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "400 16px/24px var(--font-ui)",
      color: "rgba(255,255,255,0.7)",
      margin: "0 0 24px"
    }
  }, a.line), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, a.points.map(p => /*#__PURE__*/React.createElement("div", {
    key: p,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement(IconBox, {
    name: "check",
    tint: "onDark",
    size: 30,
    icon: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "400 15px/1.3 var(--font-ui)",
      color: "rgba(255,255,255,0.92)"
    }
  }, p))))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "rgba(255,255,255,0.05)",
      border: "1px solid var(--border-on-dark)",
      borderRadius: "var(--radius-xl)",
      padding: 36,
      display: "flex",
      flexDirection: "column",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "700 11px/1.5 var(--font-ui)",
      letterSpacing: "0.8px",
      textTransform: "uppercase",
      color: "var(--color-mint)"
    }
  }, "Resolution rate"), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "300 72px/1 var(--font-display)",
      letterSpacing: "-2px",
      color: "#fff",
      margin: "14px 0 0"
    }
  }, "92%"), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: "rgba(255,255,255,0.1)",
      margin: "22px 0"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "400 15px/22px var(--font-ui)",
      color: "rgba(255,255,255,0.7)"
    }
  }, "Resolved end-to-end without a human handoff \u2014 for the ", a.key.toLowerCase(), " workflow, on your existing EHR.")))));
};
window.PlatformDark = PlatformDark;
Object.assign(__ds_scope, { PlatformDark });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/PlatformDark.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Primitives.jsx
try { (() => {
// SpinSci UI Kit — primitives: Button, Eyebrow, IconBox, Icon
// Lucide-style 2px outline icons inlined for reliability.
const SpinIcon = ({
  name,
  size = 22,
  color = "currentColor",
  strokeWidth = 2
}) => {
  const paths = {
    arrow: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M5 12h14"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M13 6l6 6-6 6"
    })),
    plus: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M12 5v14"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M5 12h14"
    })),
    check: /*#__PURE__*/React.createElement("path", {
      d: "M20 6 9 17l-5-5"
    }),
    calendar: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M8 2v4M16 2v4M3 10h18"
    }), /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "4",
      width: "18",
      height: "18",
      rx: "2"
    })),
    phone: /*#__PURE__*/React.createElement("path", {
      d: "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"
    }),
    pill: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "m10.5 20.5-7-7a5 5 0 0 1 7-7l7 7a5 5 0 0 1-7 7Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "m8.5 8.5 7 7"
    })),
    message: /*#__PURE__*/React.createElement("path", {
      d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
    }),
    shield: /*#__PURE__*/React.createElement("path", {
      d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"
    }),
    refresh: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M3 12a9 9 0 0 1 15-6.7L21 8"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M21 3v5h-5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M21 12a9 9 0 0 1-15 6.7L3 16"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 21v-5h5"
    })),
    route: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "6",
      cy: "19",
      r: "3"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "18",
      cy: "5",
      r: "3"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M12 19h4.5a3.5 3.5 0 0 0 0-7h-8a3.5 3.5 0 0 1 0-7H12"
    })),
    bolt: /*#__PURE__*/React.createElement("path", {
      d: "M13 2 3 14h7v8l10-12h-7V2z"
    }),
    heart: /*#__PURE__*/React.createElement("path", {
      d: "M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"
    }),
    user: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "8",
      r: "4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M4 21v-1a8 8 0 0 1 16 0v1"
    })),
    clock: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "9"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M12 7v5l3 2"
    })),
    star: /*#__PURE__*/React.createElement("path", {
      d: "m12 2 3 6.5 7 .9-5 4.8 1.3 7L12 18l-6.6 3.2L6.7 14l-5-4.8 7-.9z"
    }),
    sparkle: /*#__PURE__*/React.createElement("path", {
      d: "M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"
    }),
    menu: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M3 6h18M3 12h18M3 18h18"
    }))
  };
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, paths[name] || paths.arrow);
};
const Eyebrow = ({
  children,
  onDark = false
}) => /*#__PURE__*/React.createElement("span", {
  style: {
    display: "inline-block",
    fontFamily: "var(--font-ui)",
    fontWeight: 700,
    fontSize: 12,
    lineHeight: "18px",
    letterSpacing: "0.96px",
    textTransform: "uppercase",
    color: onDark ? "#fff" : "var(--color-violet)",
    background: onDark ? "transparent" : "#fff",
    border: `1px solid ${onDark ? "var(--border-on-dark-md)" : "var(--border-violet)"}`,
    borderRadius: "var(--radius-xs)",
    padding: "8px 16px"
  }
}, children);
const IconBox = ({
  name,
  tint = "mint",
  size = 40,
  icon = 22
}) => {
  const map = {
    mint: {
      bg: "var(--color-mint-subtle)",
      fg: "var(--color-teal)"
    },
    violet: {
      bg: "var(--color-violet-subtle)",
      fg: "var(--color-violet)"
    },
    onDark: {
      bg: "rgba(92,224,176,0.14)",
      fg: "var(--color-mint)"
    }
  };
  const c = map[tint] || map.mint;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: size,
      height: size,
      borderRadius: "var(--radius-sm)",
      background: c.bg,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flex: "none"
    }
  }, /*#__PURE__*/React.createElement(SpinIcon, {
    name: name,
    size: icon,
    color: c.fg
  }));
};
const Button = ({
  children,
  variant = "primary",
  icon = "arrow",
  onClick,
  size = "md"
}) => {
  const base = {
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    cursor: "pointer",
    borderRadius: "var(--radius-pill)",
    fontFamily: "var(--font-ui)",
    fontWeight: 600,
    fontSize: size === "lg" ? 15 : 14,
    lineHeight: 1,
    transition: "opacity 150ms ease, background 150ms ease",
    padding: size === "lg" ? "15px 16px 15px 24px" : "12px 12px 12px 20px",
    border: "none",
    whiteSpace: "nowrap"
  };
  const variants = {
    primary: {
      background: "var(--color-navy)",
      color: "#fff"
    },
    secondary: {
      background: "var(--color-surface)",
      color: "var(--color-navy)",
      border: "1px solid var(--border-hairline)"
    },
    ghost: {
      background: "#fff",
      color: "var(--color-navy)",
      border: "1px solid var(--border-hairline)"
    },
    onDark: {
      background: "#fff",
      color: "var(--color-ink)"
    }
  };
  const icBg = variant === "primary" || variant === "onDark" ? variant === "primary" ? "rgba(255,255,255,0.16)" : "rgba(9,19,34,0.08)" : "rgba(9,19,34,0.06)";
  return /*#__PURE__*/React.createElement("button", {
    style: {
      ...base,
      ...variants[variant]
    },
    onClick: onClick,
    onMouseDown: e => e.currentTarget.style.opacity = 0.82,
    onMouseUp: e => e.currentTarget.style.opacity = 1,
    onMouseLeave: e => e.currentTarget.style.opacity = 1
  }, children, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      width: 22,
      height: 22,
      borderRadius: "50%",
      background: icBg,
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(SpinIcon, {
    name: icon,
    size: 13,
    strokeWidth: 2.5
  })));
};
const Primitives = {
  SpinIcon,
  Eyebrow,
  IconBox,
  Button
};
Object.assign(window, {
  SpinIcon,
  Eyebrow,
  IconBox,
  Button
});
Object.assign(__ds_scope, { SpinIcon, Eyebrow, IconBox, Button, Primitives });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Primitives.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Sections.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// SpinSci UI Kit — testimonial (asymmetric dark quote card) + resources grid + footer
const Testimonial = () => /*#__PURE__*/React.createElement("section", {
  style: {
    background: "var(--color-surface)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    maxWidth: "var(--max-content)",
    margin: "0 auto",
    padding: "80px var(--gutter)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    background: "var(--color-ink)",
    color: "#fff",
    borderRadius: "16px 16px 32px 32px",
    padding: "56px 56px 48px",
    display: "grid",
    gridTemplateColumns: "1.4fr 0.6fr",
    gap: 48,
    alignItems: "center"
  }
}, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, {
  onDark: true
}, "Why SpinSci"), /*#__PURE__*/React.createElement("blockquote", {
  style: {
    font: "300 32px/1.45 var(--font-display)",
    letterSpacing: "-0.8px",
    color: "#fff",
    margin: "24px 0 28px",
    textWrap: "balance"
  }
}, "\"SpinSci took our average hold time from minutes to seconds \u2014 without changing a single EHR workflow our staff already trusted.\""), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    gap: 8
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.2)",
    borderRadius: "var(--radius-sm)",
    padding: "8px 13px",
    font: "400 13px/1 var(--font-ui)",
    color: "rgba(255,255,255,0.9)"
  }
}, "VP, Patient Access"), /*#__PURE__*/React.createElement("span", {
  style: {
    background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.2)",
    borderRadius: "var(--radius-sm)",
    padding: "8px 13px",
    font: "400 13px/1 var(--font-ui)",
    color: "rgba(255,255,255,0.9)"
  }
}, "Regional Health System"))), /*#__PURE__*/React.createElement("div", {
  style: {
    borderLeft: "1px solid rgba(255,255,255,0.12)",
    paddingLeft: 40
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    font: "300 64px/1 var(--font-display)",
    letterSpacing: "-1.5px",
    color: "#fff"
  }
}, "\u221274%"), /*#__PURE__*/React.createElement("div", {
  style: {
    font: "700 11px/1.5 var(--font-ui)",
    letterSpacing: "0.8px",
    textTransform: "uppercase",
    color: "var(--color-mint)",
    marginTop: 12
  }
}, "Average hold time")))));
const RESOURCES = [{
  cat: "Guide",
  grad: "linear-gradient(135deg, #091322, #1A3A52)",
  title: "Reducing call volume with AI agents",
  read: "6 min read"
}, {
  cat: "Case study",
  grad: "radial-gradient(120% 120% at 80% 0%, rgba(92,224,176,0.55), #122643)",
  title: "165 clinics, one access layer",
  read: "4 min read"
}, {
  cat: "Product",
  grad: "linear-gradient(135deg, #5136A9, #122643)",
  title: "Pharmacy refills, fully automated",
  read: "3 min read"
}];
const Resources = () => /*#__PURE__*/React.createElement("section", {
  style: {
    background: "var(--color-white)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    maxWidth: "var(--max-content)",
    margin: "0 auto",
    padding: "80px var(--gutter)"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
    marginBottom: 40
  }
}, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "Resources"), /*#__PURE__*/React.createElement("h2", {
  style: {
    font: "300 48px/52px var(--font-display)",
    letterSpacing: "-1.9px",
    color: "var(--color-ink)",
    margin: "20px 0 0"
  }
}, "From the team.")), /*#__PURE__*/React.createElement(Button, {
  variant: "secondary",
  icon: "arrow"
}, "View all")), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 24
  }
}, RESOURCES.map(r => /*#__PURE__*/React.createElement(ResourceCard, _extends({
  key: r.title
}, r))))));
const ResourceCard = ({
  cat,
  grad,
  title,
  read
}) => {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "block",
      textDecoration: "none",
      background: "#fff",
      border: "1px solid var(--border-faint)",
      borderRadius: "var(--radius-md)",
      overflow: "hidden",
      transform: hover ? "translateY(-2px)" : "none",
      boxShadow: hover ? "var(--shadow-card)" : "none",
      transition: "transform 200ms ease, box-shadow 200ms ease"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 150,
      background: grad,
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 14,
      left: 14,
      background: "rgba(18,38,67,0.7)",
      color: "#fff",
      borderRadius: 6,
      padding: "5px 11px",
      font: "600 10px/1 var(--font-ui)",
      letterSpacing: "0.5px",
      textTransform: "uppercase"
    }
  }, cat)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      font: "300 22px/1.2 var(--font-display)",
      letterSpacing: "-0.6px",
      color: "var(--color-ink)",
      margin: "0 0 12px"
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "400 12px/1 var(--font-ui)",
      color: "var(--color-text-secondary)"
    }
  }, read)));
};
const Footer = () => {
  const cols = {
    Platform: ["Scheduling", "Billing", "Pharmacy", "Referrals"],
    Solutions: ["Health systems", "Medical groups", "Contact centers"],
    Company: ["About", "Customers", "Careers", "Contact"]
  };
  return /*#__PURE__*/React.createElement("footer", {
    style: {
      background: "var(--color-ink)",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--max-content)",
      margin: "0 auto",
      padding: "64px var(--gutter) 40px",
      display: "grid",
      gridTemplateColumns: "1.5fr 1fr 1fr 1fr",
      gap: 40
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/spinsci-logo-white.svg",
    alt: "SpinSci",
    style: {
      height: 26
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "400 14px/21px var(--font-ui)",
      color: "rgba(255,255,255,0.6)",
      margin: "18px 0 0",
      maxWidth: 260
    }
  }, "Removing every point of friction in patient access.")), Object.entries(cols).map(([h, items]) => /*#__PURE__*/React.createElement("div", {
    key: h
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "700 11px/1 var(--font-ui)",
      letterSpacing: "0.8px",
      textTransform: "uppercase",
      color: "rgba(255,255,255,0.4)",
      marginBottom: 16
    }
  }, h), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 11
    }
  }, items.map(i => /*#__PURE__*/React.createElement("a", {
    key: i,
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      font: "400 14px/1 var(--font-ui)",
      color: "rgba(255,255,255,0.78)",
      textDecoration: "none"
    }
  }, i)))))), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--max-content)",
      margin: "0 auto",
      padding: "20px var(--gutter)",
      borderTop: "1px solid rgba(255,255,255,0.1)",
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      font: "400 12px/1 var(--font-ui)",
      color: "rgba(255,255,255,0.4)"
    }
  }, "\xA9 2026 SpinSci. All rights reserved."), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "400 12px/1 var(--font-ui)",
      color: "rgba(255,255,255,0.4)"
    }
  }, "HIPAA-ready \xB7 SOC 2 Type II")));
};
const Sections = {
  Testimonial,
  Resources,
  Footer
};
Object.assign(window, {
  Testimonial,
  Resources,
  Footer
});
Object.assign(__ds_scope, { Testimonial, Resources, Footer, Sections });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Sections.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/StatBand.jsx
try { (() => {
// SpinSci UI Kit — stat band (3 dark stat cards + 1 mint CTA) with count-up
const useCountUp = (target, run) => {
  const [val, setVal] = React.useState(0);
  React.useEffect(() => {
    if (!run) return;
    const dur = 1400,
      t0 = Date.now();
    const id = setInterval(() => {
      const p = Math.min((Date.now() - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(target * eased);
      if (p >= 1) clearInterval(id);
    }, 33);
    return () => clearInterval(id);
  }, [run, target]);
  return val;
};
const StatCard = ({
  value,
  suffix,
  label,
  run
}) => {
  const v = useCountUp(value, run);
  const display = value >= 1000000 ? (v / 1000000).toFixed(0) : Math.round(v);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--color-ink)",
      color: "#fff",
      borderRadius: "var(--radius-lg)",
      padding: 30
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "300 56px/1 var(--font-display)",
      letterSpacing: "-1.5px"
    }
  }, display, suffix), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: "rgba(255,255,255,0.1)",
      margin: "20px 0 12px"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "700 11px/1.5 var(--font-ui)",
      letterSpacing: "0.8px",
      textTransform: "uppercase",
      color: "rgba(255,255,255,0.6)"
    }
  }, label));
};
const StatBand = ({
  onDemo
}) => {
  const ref = React.useRef(null);
  const [run, setRun] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.__PRINT_MODE__) {
      setRun(true);
      return;
    }
    const poll = setInterval(() => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      if (r.top < vh * 0.85 && r.bottom > 0) {
        setRun(true);
        clearInterval(poll);
      }
    }, 150);
    return () => clearInterval(poll);
  }, []);
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--color-white)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    ref: ref,
    style: {
      maxWidth: "var(--max-content)",
      margin: "0 auto",
      padding: "80px var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 560,
      marginBottom: 44
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "By the Numbers"), /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "300 48px/52px var(--font-display)",
      letterSpacing: "-1.9px",
      color: "var(--color-ink)",
      margin: "20px 0 0"
    }
  }, "Proven at scale.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement(StatCard, {
    value: 165,
    suffix: "",
    label: "Health systems live",
    run: run
  }), /*#__PURE__*/React.createElement(StatCard, {
    value: 400000000,
    suffix: "M+",
    label: "Interactions automated",
    run: run
  }), /*#__PURE__*/React.createElement(StatCard, {
    value: 60000000,
    suffix: "M",
    label: "Patients reached",
    run: run
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--color-success-bg)",
      border: "1px solid var(--border-teal)",
      borderRadius: "var(--radius-lg)",
      padding: 30,
      display: "flex",
      flexDirection: "column"
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      font: "300 26px/1.1 var(--font-display)",
      letterSpacing: "-0.8px",
      color: "var(--color-ink)",
      margin: 0
    }
  }, "See it on your workflows."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "auto",
      paddingTop: 20
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    icon: "arrow",
    onClick: onDemo
  }, "Book a demo"))))));
};
window.StatBand = StatBand;
Object.assign(__ds_scope, { StatBand });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/StatBand.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Features = __ds_scope.Features;

__ds_ns.Hero = __ds_scope.Hero;

__ds_ns.Nav = __ds_scope.Nav;

__ds_ns.PlatformDark = __ds_scope.PlatformDark;

__ds_ns.SpinIcon = __ds_scope.SpinIcon;

__ds_ns.Eyebrow = __ds_scope.Eyebrow;

__ds_ns.IconBox = __ds_scope.IconBox;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Primitives = __ds_scope.Primitives;

__ds_ns.Testimonial = __ds_scope.Testimonial;

__ds_ns.Resources = __ds_scope.Resources;

__ds_ns.Footer = __ds_scope.Footer;

__ds_ns.Sections = __ds_scope.Sections;

__ds_ns.StatBand = __ds_scope.StatBand;

})();
