import type { ModuleMeta } from "../lib/api";
import { DataTable } from "./DataTable";
import { KeyValueCard } from "./KeyValueCard";
import { RawViewer } from "./RawViewer";
import { Timeline } from "./Timeline";

/** Picks the right renderer purely from shape + declared format — this single dispatch
 * is what covers all ~57 parsers/analysers without a bespoke component per module.
 * jsonl (is_timeline) -> Timeline, json list-of-dicts -> DataTable, json dict -> KeyValueCard,
 * anything else (gpx/kml/csv/txt/md/html) -> RawViewer with a download link. */
export function ModuleOutput({ meta, data }: { meta: ModuleMeta; data: unknown }) {
  if (meta.is_timeline && Array.isArray(data)) {
    return <Timeline events={data as never} />;
  }
  if (Array.isArray(data)) {
    if (data.length > 0 && typeof data[0] === "object" && data[0] !== null) {
      return <DataTable rows={data as Record<string, unknown>[]} />;
    }
    return (
      <ul>
        {(data as unknown[]).map((v, i) => (
          <li key={i} className="mono">
            {String(v)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof data === "object" && data !== null) {
    return <KeyValueCard data={data as Record<string, unknown>} />;
  }
  return <RawViewer text={String(data)} format={meta.format} />;
}
