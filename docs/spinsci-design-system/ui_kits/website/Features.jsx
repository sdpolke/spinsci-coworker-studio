// SpinSci UI Kit — feature grid (2-up light cards with hover lift)
const FEATURES = [
  { icon: "calendar", tint: "mint", title: "Self-scheduling", body: "Patients book, reschedule, and confirm appointments without a call — written straight to your EHR." },
  { icon: "phone", tint: "violet", title: "Contact center assist", body: "A 360° patient view surfaces the right context to agents the moment a call connects." },
  { icon: "pill", tint: "mint", title: "Pharmacy & refills", body: "Refill requests, prior-auth status, and med questions resolved automatically, day or night." },
  { icon: "route", tint: "violet", title: "Referrals & transfers", body: "Route referrals and inter-facility transfers without the fax-and-phone-tag." },
];

const FeatureCard = ({ icon, tint, title, body }) => {
  const [hover, setHover] = React.useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ background: "#fff", border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-lg)", padding: 32,
        boxShadow: hover ? "var(--shadow-card-hover)" : "var(--shadow-card)",
        transform: hover ? "translateY(-2px)" : "none",
        transition: "transform 200ms ease, box-shadow 200ms ease" }}>
      <IconBox name={icon} tint={tint} />
      <h3 style={{ font: "300 28px/1.05 var(--font-display)", letterSpacing: "-0.9px",
        color: "var(--color-ink)", margin: "20px 0 10px" }}>{title}</h3>
      <p style={{ font: "400 15px/23px var(--font-ui)", color: "var(--color-text-secondary)", margin: 0 }}>{body}</p>
    </div>
  );
};

export const Features = () => (
  <section style={{ background: "var(--color-surface)" }}>
    <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "80px var(--gutter)" }}>
      <div style={{ maxWidth: 620, marginBottom: 48 }}>
        <Eyebrow>The Platform</Eyebrow>
        <h2 style={{ font: "300 48px/52px var(--font-display)", letterSpacing: "-1.9px",
          color: "var(--color-ink)", margin: "20px 0 0", textWrap: "balance" }}>
          One access layer across every patient touchpoint.
        </h2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {FEATURES.map(f => <FeatureCard key={f.title} {...f} />)}
      </div>
    </div>
  </section>
);
window.Features = Features;
