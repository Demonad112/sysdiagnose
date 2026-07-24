import { useMemo, useState } from "react";

function stringify(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Generic sortable/filterable table for any list of flat(ish) records — this is what
 * makes every tabular parser output (ps, apps, wifi networks, ...) browsable without a
 * bespoke renderer per parser. */
export function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = useMemo(() => {
    const cols = new Set<string>();
    for (const row of rows.slice(0, 200)) Object.keys(row).forEach((k) => cols.add(k));
    return [...cols];
  }, [rows]);

  const [filter, setFilter] = useState("");
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<1 | -1>(1);

  const filtered = useMemo(() => {
    let result = rows;
    if (filter.trim()) {
      const q = filter.toLowerCase();
      result = result.filter((row) => columns.some((c) => stringify(row[c]).toLowerCase().includes(q)));
    }
    if (sortCol) {
      result = [...result].sort((a, b) => {
        const av = stringify(a[sortCol]);
        const bv = stringify(b[sortCol]);
        return av.localeCompare(bv, undefined, { numeric: true }) * sortDir;
      });
    }
    return result;
  }, [rows, columns, filter, sortCol, sortDir]);

  function toggleSort(col: string) {
    if (sortCol === col) setSortDir(sortDir === 1 ? -1 : 1);
    else {
      setSortCol(col);
      setSortDir(1);
    }
  }

  if (rows.length === 0) return <p className="muted">No rows.</p>;

  return (
    <div>
      <div style={{ marginBottom: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <input
          type="search"
          placeholder="Filter rows..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ width: 280 }}
        />
        <span className="muted">
          {filtered.length} / {rows.length} rows
        </span>
      </div>
      <div style={{ overflow: "auto", maxHeight: "72vh" }}>
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} onClick={() => toggleSort(c)}>
                  {c} {sortCol === c ? (sortDir === 1 ? "▲" : "▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 2000).map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} title={stringify(row[c])}>
                    {stringify(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length > 2000 && <p className="muted">Showing first 2000 of {filtered.length} rows — narrow with a filter to see more precisely.</p>}
      </div>
    </div>
  );
}
