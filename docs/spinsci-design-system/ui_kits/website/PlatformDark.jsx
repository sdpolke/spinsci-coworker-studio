// SpinSci UI Kit — dark platform section with tabbed agents (navy→teal gradient)
const AGENTS = [
  { key: "Scheduling", icon: "calendar", line: "Books, reschedules, and confirms across service lines.",
    points: ["Real-time EHR slot lookup", "Multi-visit coordination", "Automated reminders & confirmations"] },
  { key: "Billing", icon: "bolt", line: "Resolves balance, estimate, and payment questions.",
    points: ["Itemized balance explanations", "Pay-by-text links", "Financial-assistance routing"] },
  { key: "Pharmacy", icon: "pill", line: "Handles refills, status, and medication questions.",
    points: ["Refill request intake", "Prior-auth status checks", "Pharmacy handoff when needed"] },
  { key: "Referrals", icon: "route", line: "Moves referrals and transfers without the phone tag.",
    points: ["Specialist matching", "Inter-facility transfer intake", "Status tracking end-to-end"] },
];

export const PlatformDark = () => {
  const [active, setActive] = React.useState(0);
  const a = AGENTS[active];
  return (
    <section style={{ background: "var(--gradient-platform-bg)", color: "#fff" }}>
      <div style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "80px var(--gutter)" }}>
        <div style={{ maxWidth: 640, marginBottom: 44 }}>
          <Eyebrow onDark>AI Agents</Eyebrow>
          <h2 style={{ font: "300 48px/52px var(--font-display)", letterSpacing: "-1.9px",
            color: "#fff", margin: "20px 0 0", textWrap: "balance" }}>
            Purpose-built agents for every access workflow.
          </h2>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 28 }}>
          {AGENTS.map((ag, i) => (
            <button key={ag.key} onClick={() => setActive(i)} style={{
              display: "inline-flex", alignItems: "center", gap: 9, cursor: "pointer",
              borderRadius: "var(--radius-pill)", padding: "10px 18px",
              font: "600 14px/1 var(--font-ui)",
              background: i === active ? "#fff" : "rgba(255,255,255,0.06)",
              color: i === active ? "var(--color-ink)" : "rgba(255,255,255,0.75)",
              border: `1px solid ${i === active ? "#fff" : "rgba(255,255,255,0.16)"}`,
              transition: "all 180ms ease" }}>
              <SpinIcon name={ag.icon} size={16} strokeWidth={2}
                color={i === active ? "var(--color-teal)" : "var(--color-mint)"} />
              {ag.key}
            </button>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, alignItems: "stretch" }}>
          <div style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-on-dark)",
            borderRadius: "var(--radius-xl)", padding: 36 }}>
            <h3 style={{ font: "300 32px/1.05 var(--font-display)", letterSpacing: "-1px",
              color: "#fff", margin: "0 0 12px" }}>{a.key} agent</h3>
            <p style={{ font: "400 16px/24px var(--font-ui)", color: "rgba(255,255,255,0.7)", margin: "0 0 24px" }}>{a.line}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {a.points.map(p => (
                <div key={p} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <IconBox name="check" tint="onDark" size={30} icon={16} />
                  <span style={{ font: "400 15px/1.3 var(--font-ui)", color: "rgba(255,255,255,0.92)" }}>{p}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-on-dark)",
            borderRadius: "var(--radius-xl)", padding: 36, display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div style={{ font: "700 11px/1.5 var(--font-ui)", letterSpacing: "0.8px", textTransform: "uppercase",
              color: "var(--color-mint)" }}>Resolution rate</div>
            <div style={{ font: "300 72px/1 var(--font-display)", letterSpacing: "-2px", color: "#fff", margin: "14px 0 0" }}>92%</div>
            <div style={{ height: 1, background: "rgba(255,255,255,0.1)", margin: "22px 0" }} />
            <div style={{ font: "400 15px/22px var(--font-ui)", color: "rgba(255,255,255,0.7)" }}>
              Resolved end-to-end without a human handoff — for the {a.key.toLowerCase()} workflow, on your existing EHR.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
window.PlatformDark = PlatformDark;
