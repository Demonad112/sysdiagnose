import { Link, useLocation, useParams } from "react-router-dom";

import type { CaseOverview } from "../lib/api";
import { StatusBadge } from "./StatusBadge";

export function CategoryNav({ overview }: { overview: CaseOverview }) {
  const { caseId, moduleName } = useParams();
  const location = useLocation();
  const onUnparsed = location.pathname.endsWith("/unparsed");

  return (
    <>
      {overview.categories.map((cat) => (
        <div className="sidebar-section" key={cat.id}>
          <div className="sidebar-section-label">{cat.label}</div>
          {cat.modules.map((m) => (
            <Link
              key={m.name}
              to={`/cases/${caseId}/m/${m.name}`}
              className={`sidebar-link${moduleName === m.name ? " active" : ""}`}
            >
              <span>{m.name}</span>
              <span className="count">
                {m.status === "pending" ? "" : m.num_events || <StatusBadge status={m.status} />}
              </span>
            </Link>
          ))}
        </div>
      ))}
      <div className="sidebar-section">
        <div className="sidebar-section-label">Other</div>
        <Link to={`/cases/${caseId}/unparsed`} className={`sidebar-link${onUnparsed ? " active" : ""}`}>
          <span>Unparsed / Raw</span>
          <span className="count">{overview.unparsed_count}</span>
        </Link>
      </div>
    </>
  );
}
