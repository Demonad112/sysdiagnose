import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { api } from "../lib/api";

export function UnparsedPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [rows, setRows] = useState<{ path: string; size: number | null }[] | null>(null);

  useEffect(() => {
    if (!caseId) return;
    api.getUnparsed(caseId).then(setRows);
  }, [caseId]);

  return (
    <div>
      <h2>Unparsed / Raw files</h2>
      <p className="muted">
        Files found in the extracted sysdiagnose that no parser in the framework recognizes. Nothing here was
        dropped — download the archive to inspect these manually if needed.
      </p>
      {!rows && <p className="muted">Loading…</p>}
      {rows && <DataTable rows={rows} />}
    </div>
  );
}
