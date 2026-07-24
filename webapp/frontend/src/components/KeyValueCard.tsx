function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

/** For dict-shaped (non-list) json output — device summaries, single-record parsers. */
export function KeyValueCard({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="muted">No data.</p>;
  return (
    <div className="card">
      <dl className="kv-grid">
        {entries.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{renderValue(v)}</pre>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
