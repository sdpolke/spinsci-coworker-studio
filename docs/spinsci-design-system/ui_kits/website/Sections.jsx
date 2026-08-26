// SpinSci UI Kit — testimonial (asymmetric dark quote card) + resources grid + footer
export const Testimonial = () => (
  <section style={{ background: "var(--color-surface)" }}>
    <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "80px var(--gutter)" }}>
      <div style={{ background: "var(--color-ink)", color: "#fff", borderRadius: "16px 16px 32px 32px",
        padding: "56px 56px 48px", display: "grid", gridTemplateColumns: "1.4fr 0.6fr", gap: 48, alignItems: "center" }}>
        <div>
          <Eyebrow onDark>Why SpinSci</Eyebrow>
          <blockquote style={{ font: "300 32px/1.45 var(--font-display)", letterSpacing: "-0.8px",
            color: "#fff", margin: "24px 0 28px", textWrap: "balance" }}>
            "SpinSci took our average hold time from minutes to seconds — without changing a single
            EHR workflow our staff already trusted."
          </blockquote>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.2)",
              borderRadius: "var(--radius-sm)", padding: "8px 13px", font: "400 13px/1 var(--font-ui)", color: "rgba(255,255,255,0.9)" }}>VP, Patient Access</span>
            <span style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.2)",
              borderRadius: "var(--radius-sm)", padding: "8px 13px", font: "400 13px/1 var(--font-ui)", color: "rgba(255,255,255,0.9)" }}>Regional Health System</span>
          </div>
        </div>
        <div style={{ borderLeft: "1px solid rgba(255,255,255,0.12)", paddingLeft: 40 }}>
          <div style={{ font: "300 64px/1 var(--font-display)", letterSpacing: "-1.5px", color: "#fff" }}>−74%</div>
          <div style={{ font: "700 11px/1.5 var(--font-ui)", letterSpacing: "0.8px", textTransform: "uppercase",
            color: "var(--color-mint)", marginTop: 12 }}>Average hold time</div>
        </div>
      </div>
    </div>
  </section>
);

const RESOURCES = [
  { cat: "Guide", grad: "linear-gradient(135deg, #091322, #1A3A52)", title: "Reducing call volume with AI agents", read: "6 min read" },
  { cat: "Case study", grad: "radial-gradient(120% 120% at 80% 0%, rgba(92,224,176,0.55), #122643)", title: "165 clinics, one access layer", read: "4 min read" },
  { cat: "Product", grad: "linear-gradient(135deg, #5136A9, #122643)", title: "Pharmacy refills, fully automated", read: "3 min read" },
];

export const Resources = () => (
  <section style={{ background: "var(--color-white)" }}>
    <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "80px var(--gutter)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 40 }}>
        <div>
          <Eyebrow>Resources</Eyebrow>
          <h2 style={{ font: "300 48px/52px var(--font-display)", letterSpacing: "-1.9px",
            color: "var(--color-ink)", margin: "20px 0 0" }}>From the team.</h2>
        </div>
        <Button variant="secondary" icon="arrow">View all</Button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 }}>
        {RESOURCES.map(r => <ResourceCard key={r.title} {...r} />)}
      </div>
    </div>
  </section>
);

const ResourceCard = ({ cat, grad, title, read }) => {
  const [hover, setHover] = React.useState(false);
  return (
    <a href="#" onClick={e => e.preventDefault()}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: "block", textDecoration: "none", background: "#fff",
        border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", overflow: "hidden",
        transform: hover ? "translateY(-2px)" : "none", boxShadow: hover ? "var(--shadow-card)" : "none",
        transition: "transform 200ms ease, box-shadow 200ms ease" }}>
      <div style={{ height: 150, background: grad, position: "relative" }}>
        <span style={{ position: "absolute", top: 14, left: 14, background: "rgba(18,38,67,0.7)",
          color: "#fff", borderRadius: 6, padding: "5px 11px", font: "600 10px/1 var(--font-ui)",
          letterSpacing: "0.5px", textTransform: "uppercase" }}>{cat}</span>
      </div>
      <div style={{ padding: 20 }}>
        <h3 style={{ font: "300 22px/1.2 var(--font-display)", letterSpacing: "-0.6px",
          color: "var(--color-ink)", margin: "0 0 12px" }}>{title}</h3>
        <div style={{ font: "400 12px/1 var(--font-ui)", color: "var(--color-text-secondary)" }}>{read}</div>
      </div>
    </a>
  );
};

export const Footer = () => {
  const cols = {
    Platform: ["Scheduling", "Billing", "Pharmacy", "Referrals"],
    Solutions: ["Health systems", "Medical groups", "Contact centers"],
    Company: ["About", "Customers", "Careers", "Contact"],
  };
  return (
    <footer style={{ background: "var(--color-ink)", color: "#fff" }}>
      <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "64px var(--gutter) 40px",
        display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr", gap: 40 }}>
        <div>
          <img src="../../assets/spinsci-logo-white.svg" alt="SpinSci" style={{ height: 26 }} />
          <p style={{ font: "400 14px/21px var(--font-ui)", color: "rgba(255,255,255,0.6)", margin: "18px 0 0", maxWidth: 260 }}>
            Removing every point of friction in patient access.
          </p>
        </div>
        {Object.entries(cols).map(([h, items]) => (
          <div key={h}>
            <div style={{ font: "700 11px/1 var(--font-ui)", letterSpacing: "0.8px", textTransform: "uppercase",
              color: "rgba(255,255,255,0.4)", marginBottom: 16 }}>{h}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {items.map(i => (
                <a key={i} href="#" onClick={e => e.preventDefault()} style={{ font: "400 14px/1 var(--font-ui)",
                  color: "rgba(255,255,255,0.78)", textDecoration: "none" }}>{i}</a>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "20px var(--gutter)",
        borderTop: "1px solid rgba(255,255,255,0.1)", display: "flex", justifyContent: "space-between" }}>
        <span style={{ font: "400 12px/1 var(--font-ui)", color: "rgba(255,255,255,0.4)" }}>© 2026 SpinSci. All rights reserved.</span>
        <span style={{ font: "400 12px/1 var(--font-ui)", color: "rgba(255,255,255,0.4)" }}>HIPAA-ready · SOC 2 Type II</span>
      </div>
    </footer>
  );
};
export const Sections = { Testimonial, Resources, Footer };
Object.assign(window, { Testimonial, Resources, Footer });
