// SpinSci UI Kit — top navigation (transparent over hero, frosted on scroll)
export const Nav = ({ onDemo }) => {
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
  return (
    <header style={{
      position: "sticky", top: 0, zIndex: 50,
      background: scrolled ? "rgba(255,255,255,0.95)" : "transparent",
      backdropFilter: scrolled ? "saturate(180%) blur(12px)" : "none",
      borderBottom: scrolled ? "1px solid var(--border-faint)" : "1px solid transparent",
      transition: "background 250ms ease, border-color 250ms ease",
    }}>
      <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "16px var(--gutter)",
        display: "flex", alignItems: "center", gap: 24 }}>
        <img src="../../assets/spinsci-logo.svg" alt="SpinSci" style={{ height: 28 }} />
        <nav style={{ display: "flex", gap: 4, marginLeft: 16 }} className="kit-navlinks">
          {links.map(l => (
            <a key={l} href="#" onClick={e => e.preventDefault()} style={{
              fontFamily: "var(--font-ui)", fontSize: 14, fontWeight: 500, color: "var(--color-ink)",
              textDecoration: "none", padding: "10px 14px", borderRadius: 6, transition: "background 150ms ease",
            }}
            onMouseEnter={e => e.currentTarget.style.background = "rgba(9,19,34,0.05)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>{l}</a>
          ))}
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <a href="#" onClick={e => e.preventDefault()} style={{ fontFamily: "var(--font-ui)", fontSize: 14,
            fontWeight: 600, color: "var(--color-ink)", textDecoration: "none", whiteSpace: "nowrap" }} className="kit-signin">Sign in</a>
          <Button variant="primary" icon="arrow" onClick={onDemo}>Book a demo</Button>
        </div>
      </div>
    </header>
  );
};
window.Nav = Nav;
