import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { filesFromDataTransfer, filesFromFileList } from "../lib/fileWalk";
import { uploadManager } from "../lib/uploadManager";
import { useUploadState } from "../lib/useUploadState";

export function UploadPage() {
  const navigate = useNavigate();
  const batch = useUploadState();
  const [dragActive, setDragActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const archiveInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const filesInputRef = useRef<HTMLInputElement>(null);

  const resumable = !batch ? uploadManager.getResumableInfo() : null;

  function pickArchive(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    uploadManager.addFiles(filesFromFileList(files), "archive");
    e.target.value = "";
  }

  function pickFolder(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    uploadManager.addFiles(filesFromFileList(files), "folder");
    e.target.value = "";
  }

  function pickFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    // additional loose files merge into the same folder-mode batch as a folder pick —
    // this is the exact "folder + files together" combination the old prototype broke on
    uploadManager.addFiles(filesFromFileList(files), "folder");
    e.target.value = "";
  }

  async function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    const picked = await filesFromDataTransfer(e.dataTransfer.items);
    if (picked.length === 0) return;
    const mode = picked.length === 1 && picked[0].relativePath.endsWith(".tar.gz") ? "archive" : "folder";
    uploadManager.addFiles(picked, mode);
  }

  async function startUpload() {
    setStarting(true);
    try {
      const { caseId, jobId } = await uploadManager.start();
      navigate(`/jobs/${jobId}?case=${caseId}`);
    } catch {
      setStarting(false);
    }
  }

  const totalBytes = batch?.items.reduce((s, i) => s + i.size, 0) ?? 0;
  const sentBytes =
    batch?.items.reduce((s, i) => s + Math.min(i.sentChunks.length * (i.chunkSize || 1), i.size), 0) ?? 0;
  const overallPct = totalBytes > 0 ? Math.round((sentBytes / totalBytes) * 100) : 0;

  return (
    <div className="main" style={{ width: "100%", maxWidth: 900 }}>
      <h2>New case</h2>

      {resumable && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--warn)" }}>
          <p>
            Found an interrupted <strong>{resumable.mode}</strong> upload ({resumable.fileCount} file
            {resumable.fileCount === 1 ? "" : "s"}) from before this page was reloaded. Re-select the same file
            {resumable.fileCount === 1 ? "" : "s"}/folder below and upload will resume from where it left off —
            already-sent chunks won't be re-sent.{" "}
            <button className="secondary" onClick={() => uploadManager.discardResumable()}>
              Discard instead
            </button>
          </p>
        </div>
      )}

      <div style={{ display: "flex", gap: 24, marginBottom: 20 }}>
        <div className="card" style={{ flex: 1 }}>
          <h4 style={{ marginTop: 0 }}>Full archive (.tar.gz)</h4>
          <p className="muted">A single sysdiagnose .tar.gz, any size — streamed to disk in chunks.</p>
          <input ref={archiveInputRef} type="file" accept=".tar.gz" onChange={pickArchive} style={{ display: "none" }} />
          <button className="secondary" onClick={() => archiveInputRef.current?.click()}>
            Choose archive…
          </button>
        </div>

        <div className="card" style={{ flex: 1 }}>
          <h4 style={{ marginTop: 0 }}>Already-extracted folder</h4>
          <p className="muted">Pick a folder, and optionally add extra loose files on top of it.</p>
          <input
            ref={folderInputRef}
            type="file"
            // @ts-expect-error non-standard attribute, widely supported
            webkitdirectory=""
            multiple
            onChange={pickFolder}
            style={{ display: "none" }}
          />
          <input ref={filesInputRef} type="file" multiple onChange={pickFiles} style={{ display: "none" }} />
          <button className="secondary" onClick={() => folderInputRef.current?.click()} style={{ marginRight: 8 }}>
            Choose folder…
          </button>
          <button className="secondary" onClick={() => filesInputRef.current?.click()}>
            + Add files…
          </button>
        </div>
      </div>

      <div
        className={`dropzone${dragActive ? " active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
      >
        Or drag & drop a .tar.gz, a folder, or a set of files here
      </div>

      {batch && batch.items.length > 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <strong>
              {batch.items.length} file{batch.items.length === 1 ? "" : "s"} ({batch.mode})
            </strong>
            <span className="muted">{overallPct}%</span>
          </div>
          <div className="progress-bar" style={{ marginBottom: 14 }}>
            <div style={{ width: `${overallPct}%` }} />
          </div>

          <div style={{ maxHeight: 240, overflow: "auto" }}>
            {batch.items.map((item) => {
              const pct = item.totalChunks > 0 ? Math.round((item.sentChunks.length / item.totalChunks) * 100) : 0;
              return (
                <div key={item.relativePath} className="timeline-row" style={{ gridTemplateColumns: "1fr 100px 60px" }}>
                  <span className="mono">{item.relativePath}</span>
                  <span className="muted">{item.status === "done" ? "done" : `${pct}%`}</span>
                  {batch.status === "idle" && (
                    <button className="secondary" onClick={() => uploadManager.removeItem(item.relativePath)}>
                      remove
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {batch.error && <p className="badge badge-error">{batch.error}</p>}

          <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
            <button onClick={startUpload} disabled={starting || batch.status === "uploading"}>
              {starting || batch.status === "uploading" ? "Uploading…" : "Start upload"}
            </button>
            <button className="secondary" onClick={() => uploadManager.reset()} disabled={batch.status === "uploading"}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
