import { useEffect, useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router-dom";

import { CategoryNav } from "../components/CategoryNav";
import { StatusBadge } from "../components/StatusBadge";
import { api, type CaseOverview } from "../lib/api";
import { SearchBox } from "../components/SearchBox";

export function CaseLayout() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<CaseOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!caseId) return;
    setOverview(null);
    api
      .getOverview(caseId)
      .then(setOverview)
      .catch((e) => setError(String(e)));
  }, [caseId]);

  async function onDelete() {
    if (!caseId || !overview) return;
    if (!window.confirm(`Permanently delete "${overview.case.display_name}" and all its uploaded data? This cannot be undone.`)) {
      return;
    }
    setDeleting(true);
    try {
      await api.deleteCase(caseId);
      navigate("/");
    } catch (e) {
      setError(String(e));
      setDeleting(false);
    }
  }

  if (error) return <div className="page">{error}</div>;
  if (!overview) return <div className="page muted">Loading case…</div>;

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar-head">
          <div className="sidebar-title">{overview.case.display_name}</div>
          <StatusBadge status={overview.case.status} />
        </div>
        <div className="sidebar-scroll">
          <CategoryNav overview={overview} />
        </div>
        <div className="sidebar-foot">
          <button className="danger block" onClick={onDelete} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete case"}
          </button>
        </div>
      </aside>
      <div className="main">
        <div className="main-toolbar">
          <SearchBox caseId={caseId!} />
        </div>
        <div className="main-scroll">
          <Outlet context={overview} />
        </div>
      </div>
    </>
  );
}
