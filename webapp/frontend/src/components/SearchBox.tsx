import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";

/** Global search across every parsed json/jsonl record for the current case. */
export function SearchBox({ caseId }: { caseId: string }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ parser: string; category: string; record: unknown }[] | null>(null);
  const [open, setOpen] = useState(false);

  async function runSearch(value: string) {
    setQ(value);
    if (value.trim().length < 2) {
      setResults(null);
      setOpen(false);
      return;
    }
    const res = await api.search(caseId, value);
    setResults(res.results);
    setOpen(true);
  }

  return (
    <div style={{ position: "relative", maxWidth: 480 }}>
      <input
        type="search"
        placeholder="Search across all parsed data…"
        value={q}
        onChange={(e) => runSearch(e.target.value)}
        onFocus={() => results && setOpen(true)}
        style={{ width: "100%" }}
      />
      {open && results && (
        <div
          className="card"
          style={{ position: "absolute", top: "110%", left: 0, right: 0, zIndex: 10, maxHeight: 360, overflow: "auto" }}
        >
          {results.length === 0 && <p className="muted">No matches.</p>}
          {results.map((r, i) => (
            <div key={i} style={{ marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid var(--border)" }}>
              <Link to={`/cases/${caseId}/m/${r.parser}`} onClick={() => setOpen(false)}>
                {r.parser}
              </Link>
              <div className="muted mono" style={{ fontSize: 11.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {JSON.stringify(r.record)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
