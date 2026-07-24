import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { ModuleOutput } from "../components/ModuleOutput";
import { api, type ModuleMeta } from "../lib/api";

export function ParserViewPage() {
  const { caseId, moduleName } = useParams<{ caseId: string; moduleName: string }>();
  const [meta, setMeta] = useState<ModuleMeta | null>(null);
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!caseId || !moduleName) return;
    setMeta(null);
    setData(null);
    setError(null);
    api
      .getParserOutput(caseId, moduleName)
      .then((res) => {
        setMeta(res.meta);
        setData(res.data);
      })
      .catch((e) => setError(String(e)));
  }, [caseId, moduleName]);

  if (error) return <p className="badge badge-error">{error}</p>;
  if (!meta) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 4 }}>
        <h2 style={{ margin: 0 }}>{moduleName}</h2>
        <span className="muted">({meta.kind})</span>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {meta.description}
      </p>
      <ModuleOutput meta={meta} data={data} />
    </div>
  );
}
