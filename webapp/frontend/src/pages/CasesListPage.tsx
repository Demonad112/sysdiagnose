import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type CaseSummary } from "../lib/api";

export function CasesListPage() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listCases().then(setCases).catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="main" style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>Cases</h2>
        <Link to="/upload">
          <button>+ New case</button>
        </Link>
      </div>

      {error && <p className="badge-error badge">{error}</p>}
      {!cases && !error && <p className="muted">Loading…</p>}
      {cases && cases.length === 0 && (
        <p className="muted">No cases yet. Upload a sysdiagnose archive or folder to get started.</p>
      )}

      <table className="data-table" style={{ maxWidth: 960 }}>
        <thead>
          <tr>
            <th>Case</th>
            <th>Status</th>
            <th>Model</th>
            <th>iOS</th>
            <th>Serial</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {cases?.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`/cases/${c.id}`}>{c.display_name}</Link>
              </td>
              <td>{c.status}</td>
              <td>{c.model ?? "—"}</td>
              <td>{c.ios_version ?? "—"}</td>
              <td>{c.serial_number ?? "—"}</td>
              <td>{new Date(c.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
