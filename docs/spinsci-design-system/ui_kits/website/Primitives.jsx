// SpinSci UI Kit — primitives: Button, Eyebrow, IconBox, Icon
// Lucide-style 2px outline icons inlined for reliability.
export const SpinIcon = ({ name, size = 22, color = "currentColor", strokeWidth = 2 }) => {
  const paths = {
    arrow: <><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></>,
    plus: <><path d="M12 5v14"/><path d="M5 12h14"/></>,
    check: <path d="M20 6 9 17l-5-5"/>,
    calendar: <><path d="M8 2v4M16 2v4M3 10h18"/><rect x="3" y="4" width="18" height="18" rx="2"/></>,
    phone: <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/>,
    pill: <><path d="m10.5 20.5-7-7a5 5 0 0 1 7-7l7 7a5 5 0 0 1-7 7Z"/><path d="m8.5 8.5 7 7"/></>,
    message: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>,
    shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>,
    refresh: <><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></>,
    route: <><circle cx="6" cy="19" r="3"/><circle cx="18" cy="5" r="3"/><path d="M12 19h4.5a3.5 3.5 0 0 0 0-7h-8a3.5 3.5 0 0 1 0-7H12"/></>,
    bolt: <path d="M13 2 3 14h7v8l10-12h-7V2z"/>,
    heart: <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a8 8 0 0 1 16 0v1"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    star: <path d="m12 2 3 6.5 7 .9-5 4.8 1.3 7L12 18l-6.6 3.2L6.7 14l-5-4.8 7-.9z"/>,
    sparkle: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>,
    menu: <><path d="M3 6h18M3 12h18M3 18h18"/></>,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {paths[name] || paths.arrow}
    </svg>
  );
};

export const Eyebrow = ({ children, onDark = false }) => (
  <span style={{
    display: "inline-block", fontFamily: "var(--font-ui)", fontWeight: 700,
    fontSize: 12, lineHeight: "18px", letterSpacing: "0.96px", textTransform: "uppercase",
    color: onDark ? "#fff" : "var(--color-violet)",
    background: onDark ? "transparent" : "#fff",
    border: `1px solid ${onDark ? "var(--border-on-dark-md)" : "var(--border-violet)"}`,
    borderRadius: "var(--radius-xs)", padding: "8px 16px",
  }}>{children}</span>
);

export const IconBox = ({ name, tint = "mint", size = 40, icon = 22 }) => {
  const map = {
    mint: { bg: "var(--color-mint-subtle)", fg: "var(--color-teal)" },
    violet: { bg: "var(--color-violet-subtle)", fg: "var(--color-violet)" },
    onDark: { bg: "rgba(92,224,176,0.14)", fg: "var(--color-mint)" },
  };
  const c = map[tint] || map.mint;
  return (
    <div style={{ width: size, height: size, borderRadius: "var(--radius-sm)", background: c.bg,
      display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
      <SpinIcon name={name} size={icon} color={c.fg} />
    </div>
  );
};

export const Button = ({ children, variant = "primary", icon = "arrow", onClick, size = "md" }) => {
  const base = {
    display: "inline-flex", alignItems: "center", gap: 10, cursor: "pointer",
    borderRadius: "var(--radius-pill)", fontFamily: "var(--font-ui)", fontWeight: 600,
    fontSize: size === "lg" ? 15 : 14, lineHeight: 1, transition: "opacity 150ms ease, background 150ms ease",
    padding: size === "lg" ? "15px 16px 15px 24px" : "12px 12px 12px 20px",
    border: "none", whiteSpace: "nowrap",
  };
  const variants = {
    primary: { background: "var(--color-navy)", color: "#fff" },
    secondary: { background: "var(--color-surface)", color: "var(--color-navy)", border: "1px solid var(--border-hairline)" },
    ghost: { background: "#fff", color: "var(--color-navy)", border: "1px solid var(--border-hairline)" },
    onDark: { background: "#fff", color: "var(--color-ink)" },
  };
  const icBg = variant === "primary" || variant === "onDark"
    ? (variant === "primary" ? "rgba(255,255,255,0.16)" : "rgba(9,19,34,0.08)")
    : "rgba(9,19,34,0.06)";
  return (
    <button style={{ ...base, ...variants[variant] }}
      onClick={onClick}
      onMouseDown={e => e.currentTarget.style.opacity = 0.82}
      onMouseUp={e => e.currentTarget.style.opacity = 1}
      onMouseLeave={e => e.currentTarget.style.opacity = 1}>
      {children}
      {icon && (
        <span style={{ width: 22, height: 22, borderRadius: "50%", background: icBg,
          display: "flex", alignItems: "center", justifyContent: "center" }}>
          <SpinIcon name={icon} size={13} strokeWidth={2.5} />
        </span>
      )}
    </button>
  );
};

export const Primitives = { SpinIcon, Eyebrow, IconBox, Button };
Object.assign(window, { SpinIcon, Eyebrow, IconBox, Button });
