// SpinSci UI Kit — stat band (3 dark stat cards + 1 mint CTA) with count-up
const useCountUp = (target, run) => {
  const [val, setVal] = React.useState(0);
  React.useEffect(() => {
    if (!run) return;
    const dur = 1400, t0 = Date.now();
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

const StatCard = ({ value, suffix, label, run }) => {
  const v = useCountUp(value, run);
  const display = value >= 1000000 ? (v / 1000000).toFixed(0) : Math.round(v);
  return (
    <div style={{ background: "var(--color-ink)", color: "#fff", borderRadius: "var(--radius-lg)", padding: 30 }}>
      <div style={{ font: "300 56px/1 var(--font-display)", letterSpacing: "-1.5px" }}>{display}{suffix}</div>
      <div style={{ height: 1, background: "rgba(255,255,255,0.1)", margin: "20px 0 12px" }} />
      <div style={{ font: "700 11px/1.5 var(--font-ui)", letterSpacing: "0.8px", textTransform: "uppercase",
        color: "rgba(255,255,255,0.6)" }}>{label}</div>
    </div>
  );
};

export const StatBand = ({ onDemo }) => {
  const ref = React.useRef(null);
  const [run, setRun] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.__PRINT_MODE__) { setRun(true); return; }
    const poll = setInterval(() => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      if (r.top < vh * 0.85 && r.bottom > 0) { setRun(true); clearInterval(poll); }
    }, 150);
    return () => clearInterval(poll);
  }, []);
  return (
    <section style={{ background: "var(--color-white)" }}>
      <div ref={ref} style={{ maxWidth: "var(--max-content)", margin: "0 auto", padding: "80px var(--gutter)" }}>
        <div style={{ maxWidth: 560, marginBottom: 44 }}>
          <Eyebrow>By the Numbers</Eyebrow>
          <h2 style={{ font: "300 48px/52px var(--font-display)", letterSpacing: "-1.9px",
            color: "var(--color-ink)", margin: "20px 0 0" }}>Proven at scale.</h2>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
          <StatCard value={165} suffix="" label="Health systems live" run={run} />
          <StatCard value={400000000} suffix="M+" label="Interactions automated" run={run} />
          <StatCard value={60000000} suffix="M" label="Patients reached" run={run} />
          <div style={{ background: "var(--color-success-bg)", border: "1px solid var(--border-teal)",
            borderRadius: "var(--radius-lg)", padding: 30, display: "flex", flexDirection: "column" }}>
            <h3 style={{ font: "300 26px/1.1 var(--font-display)", letterSpacing: "-0.8px",
              color: "var(--color-ink)", margin: 0 }}>See it on your workflows.</h3>
            <div style={{ marginTop: "auto", paddingTop: 20 }}>
              <Button variant="primary" icon="arrow" onClick={onDemo}>Book a demo</Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
window.StatBand = StatBand;
