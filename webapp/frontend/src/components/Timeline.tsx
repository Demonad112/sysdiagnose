import { useMemo, useState } from "react";

interface SysdxEvent {
  datetime: string;
  message: string;
  timestamp_desc?: string;
  module?: string;
  data?: Record<string, unknown>;
}

/** Renders any jsonl (event-stream) parser output as a searchable, chronological
 * timeline — this is the shared view for logarchive, powerlogs, crashlogs, ps.txt
 * (sysdiagnose-creation-time events), etc. */
export function Timeline({ events }: { events: SysdxEvent[] }) {
  const [filter, setFilter] = useState("");

  const sorted = useMemo(
    () => [...events].sort((a, b) => (a.datetime < b.datetime ? -1 : a.datetime > b.datetime ? 1 : 0)),
    [events],
  );

  const filtered = useMemo(() => {
    if (!filter.trim()) return sorted;
    const q = filter.toLowerCase();
    return sorted.filter(
      (e) => e.message?.toLowerCase().includes(q) || JSON.stringify(e.data ?? {}).toLowerCase().includes(q),
    );
  }, [sorted, filter]);

  if (events.length === 0) return <p className="muted">No events.</p>;

  return (
    <div>
      <div style={{ marginBottom: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <input
          type="search"
          placeholder="Filter events..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ width: 280 }}
        />
        <span className="muted">
          {filtered.length} / {events.length} events
        </span>
      </div>
      <div style={{ maxHeight: "72vh", overflow: "auto" }}>
        {filtered.slice(0, 3000).map((e, i) => (
          <div className="timeline-row" key={i}>
            <div className="timeline-time">{e.datetime}</div>
            <div>
              <div>{e.message}</div>
              {e.data && Object.keys(e.data).length > 0 && (
                <div className="muted" style={{ fontSize: 11.5 }}>
                  {JSON.stringify(e.data)}
                </div>
              )}
            </div>
          </div>
        ))}
        {filtered.length > 3000 && (
          <p className="muted">Showing first 3000 of {filtered.length} events — narrow with a filter to see more.</p>
        )}
      </div>
    </div>
  );
}
