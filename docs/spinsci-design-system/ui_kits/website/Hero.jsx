// SpinSci UI Kit — Hero with ambient mint wash + floating live-call card
export const Hero = ({ onDemo }) => (
  <section style={{ position: "relative", overflow: "hidden", background: "var(--color-white)" }}>
    <div className="kit-herowash" style={{
      position: "absolute", inset: 0,
      background: "radial-gradient(110% 80% at 88% -10%, rgba(92,224,176,0.20) 0%, rgba(119,89,217,0.06) 40%, rgba(255,255,255,0) 62%)",
      pointerEvents: "none",
    }} />
    <div style={{ position: "relative", maxWidth: "var(--max-content)", margin: "0 auto",
      padding: "96px var(--gutter) 80px", display: "grid", gridTemplateColumns: "1.05fr 0.95fr",
      gap: 56, alignItems: "center" }}>
      <div>
        <Eyebrow>Patient Access, Automated</Eyebrow>
        <h1 style={{ font: "300 64px/68px var(--font-display)", letterSpacing: "-2.6px",
          color: "var(--color-ink)", margin: "24px 0 0", textWrap: "balance" }}>
          Remove every point of friction in <span className="ds-gradient-text">patient access</span>.
        </h1>
        <p style={{ font: "400 18px/27px var(--font-ui)", color: "var(--color-text-secondary)",
          margin: "22px 0 0", maxWidth: 480 }}>
          SpinSci agents resolve scheduling, billing, and pharmacy requests across your existing
          EHR — so your teams focus on care, not call queues.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
          <Button variant="primary" size="lg" icon="arrow" onClick={onDemo}>Book a demo</Button>
          <Button variant="ghost" size="lg" icon="arrow">See the platform</Button>
        </div>
        <div style={{ display: "flex", gap: 28, marginTop: 40 }}>
          {[["165", "Health systems"], ["400M+", "Interactions"], ["60M", "Patients reached"]].map(([n, l]) => (
            <div key={l}>
              <div style={{ font: "300 34px/1 var(--font-display)", letterSpacing: "-1px", color: "var(--color-ink)" }}>{n}</div>
              <div style={{ font: "700 11px/1.4 var(--font-ui)", letterSpacing: "0.6px", textTransform: "uppercase",
                color: "var(--color-text-secondary)", marginTop: 6 }}>{l}</div>
            </div>
          ))}
        </div>
      </div>
      <HeroCard />
    </div>
  </section>
);

const HeroCard = () => {
  const msgs = [
    { who: "agent", text: "Hi Maria — I can help you reschedule your cardiology visit. Does Thursday at 9:40 AM work?" },
    { who: "patient", text: "Yes, that's perfect." },
    { who: "agent", text: "Done. You're confirmed for Thu, Jun 5 · 9:40 AM. A reminder will text you the day before." },
  ];
  const [shown, setShown] = React.useState(0);
  React.useEffect(() => {
    if (shown >= msgs.length) return;
    const t = setTimeout(() => setShown(s => s + 1), shown === 0 ? 400 : 900);
    return () => clearTimeout(t);
  }, [shown]);
  return (
    <div style={{ background: "#fff", border: "1px solid var(--border-hairline)",
      borderRadius: "var(--radius-xl)", boxShadow: "var(--shadow-card)", padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 16,
        borderBottom: "1px solid var(--border-faint)" }}>
        <IconBox name="sparkle" tint="violet" size={38} icon={20} />
        <div>
          <div style={{ font: "600 14px/1 var(--font-ui)", color: "var(--color-ink)" }}>SpinSci Scheduling Agent</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--color-mint)" }} />
            <span style={{ font: "400 12px/1 var(--font-ui)", color: "var(--color-text-secondary)" }}>Live · resolving in 0:14</span>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "18px 0 4px", minHeight: 230 }}>
        {msgs.slice(0, shown).map((m, i) => (
          <div key={i} className="kit-bubble" style={{
            alignSelf: m.who === "patient" ? "flex-end" : "flex-start",
            maxWidth: "82%",
            background: m.who === "patient" ? "var(--color-navy)" : "var(--color-surface)",
            color: m.who === "patient" ? "#fff" : "var(--color-ink)",
            border: m.who === "patient" ? "none" : "1px solid var(--border-faint)",
            borderRadius: m.who === "patient" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
            padding: "12px 14px", font: "400 13px/19px var(--font-ui)",
          }}>{m.text}</div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, paddingTop: 14,
        borderTop: "1px solid var(--border-faint)" }}>
        <span style={{ font: "400 11px/1 var(--font-ui)", color: "var(--color-text-secondary)" }}>Synced to</span>
        <span style={{ font: "600 11px/1 var(--font-ui)", color: "var(--color-teal)",
          background: "var(--color-success-bg)", border: "1px solid var(--border-teal)",
          borderRadius: 6, padding: "5px 9px" }}>EHR · Appointments</span>
      </div>
    </div>
  );
};
window.Hero = Hero;
