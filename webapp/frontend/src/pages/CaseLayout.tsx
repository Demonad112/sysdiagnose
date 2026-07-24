import { useEffect, useState } from "react";
import { Link, Outlet, useParams } from "react-router-dom";

import { CategoryNav } from "../components/CategoryNav";
import { api, type CaseOverview } from "../lib/api";
import { SearchBox } from "../components/SearchBox";

export function CaseLayout() {
  const { caseId } = useParams<{ caseId: string }>();
  const [overview, setOverview] = useState<CaseOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!caseId) return;
    setOverview(null);
    api
      .getOverview(caseId)
      .then(setOverview)
      .catch((e) => setError(String(e)));
  }, [caseId]);

  if (error) return <div className="main">{error}</div>;
  if (!overview) return <div className="main">Loading case…</div>;

  return (
    <div className="app-shell">
      <div className="sidebar">
        <h1>
          <Link to="/" style={{ color: "inherit" }}>
            sysdx
          </Link>
        </h1>
        <div style={{ padding: "0 16px 12px" }}>
          <div style={{ fontWeight: 600 }}>{overview.case.display_name}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {overview.case.status}
          </div>
        </div>
        <CategoryNav overview={overview} />
      </div>
      <div className="main">
        <div style={{ marginBottom: 20 }}>
          <SearchBox caseId={caseId!} />
        </div>
        <Outlet context={overview} />
      </div>
    </div>
  );
}
