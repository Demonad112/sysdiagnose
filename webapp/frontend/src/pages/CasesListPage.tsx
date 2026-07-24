import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../components/StatusBadge";
import { api, type CaseSummary } from "../lib/api";

export function CasesListPage() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    api.listCases().then(setCases).catch((e) => setError(String(e)));
  }, []);

  async function onDelete(c: CaseSummary) {
    if (!window.confirm(`Permanently delete "${c.display_name}" and all its uploaded data? This cannot be undone.`)) {
      return;
    }
    setDeletingId(c.id);
    try {
      await api.deleteCase(c.id);
      setCases((prev) => prev?.filter((x) => x.id !== c.id) ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-header">
          <div>
            <h2 className="page-title">Cases</h2>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Uploaded sysdiagnose archives and their parsed output.
            </p>
          </div>
          <span className="muted" style={{ fontSize: 13 }}>
            {cases ? `${cases.length} case${cases.length === 1 ? "" : "s"}` : ""}
          </span>
        </div>

        {error && <p className="badge badge-error">{error}</p>}
        {!cases && !error && <p className="muted">Loading…</p>}

        {cases && cases.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">📄</div>
            <p>No cases yet.</p>
            <p className="muted">Upload a sysdiagnose archive or folder to get started.</p>
            <Link to="/upload">
              <button style={{ marginTop: 8 }}>Upload a sysdiagnose</button>
            </Link>
          </div>
        )}

        {cases && cases.length > 0 && (
          <div className="case-list">
            {cases.map((c) => (
              <div key={c.id} className="case-row">
                <Link to={`/cases/${c.id}`} className="case-row-main">
                  <div className="case-row-title">
                    <span className="case-name">{c.display_name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="case-row-meta">
                    <span>{c.model ?? "unknown model"}</span>
                    <span className="dot">·</span>
                    <span>{c.ios_version ? `iOS ${c.ios_version}` : "iOS —"}</span>
                    <span className="dot">·</span>
                    <span className="mono">{c.serial_number ?? "no serial"}</span>
                    <span className="dot">·</span>
                    <span>{new Date(c.created_at).toLocaleString()}</span>
                  </div>
                </Link>
                <button
                  className="icon-btn danger"
                  title="Delete case"
                  aria-label={`Delete ${c.display_name}`}
                  disabled={deletingId === c.id}
                  onClick={() => onDelete(c)}
                >
                  {deletingId === c.id ? "…" : "🗑"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
