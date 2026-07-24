import { useOutletContext } from "react-router-dom";

import type { CaseOverview } from "../lib/api";

export function CaseHomePage() {
  const overview = useOutletContext<CaseOverview>();
  const totalModules = overview.categories.reduce((s, c) => s + c.modules.length, 0);
  const ran = overview.categories.reduce((s, c) => s + c.modules.filter((m) => m.status !== "pending").length, 0);

  return (
    <div>
      <h2>{overview.case.display_name}</h2>
      <p className="muted">
        {ran} / {totalModules} parsers &amp; analysers ran · {overview.unparsed_count} unparsed file
        {overview.unparsed_count === 1 ? "" : "s"}
      </p>

      {overview.categories.map((cat) => (
        <div key={cat.id} className="card" style={{ marginBottom: 12 }}>
          <strong>{cat.label}</strong>
          <div className="muted" style={{ marginTop: 4 }}>
            {cat.modules.map((m) => m.name).join(", ")}
          </div>
        </div>
      ))}

      <p className="muted">Pick a module from the sidebar to view its structured output.</p>
    </div>
  );
}
