import { useEffect, useMemo } from "react";

/** Custom-format parser/analyser outputs (gpx, kml, csv, txt, md, html) that don't fit
 * the table/timeline/key-value shapes — shown as text plus a download link, rather than
 * dropped or force-fit into a table. */
export function RawViewer({ text, format }: { text: string; format: string }) {
  const url = useMemo(() => URL.createObjectURL(new Blob([text], { type: "text/plain" })), [text]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <a href={url} download={`output.${format}`}>
          Download .{format}
        </a>
      </div>
      <pre
        className="card mono"
        style={{ maxHeight: "72vh", overflow: "auto", whiteSpace: "pre-wrap", fontSize: 12.5 }}
      >
        {text}
      </pre>
    </div>
  );
}
