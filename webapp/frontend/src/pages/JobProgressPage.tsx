import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, type JobStatus } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";

export function JobProgressPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [params] = useSearchParams();
  const caseId = params.get("case");
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    async function poll() {
      try {
        const j = await api.getJob(jobId!);
        if (cancelled) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") {
          timer.current = window.setTimeout(poll, 1500);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    poll();

    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [jobId]);

  const pct = job && job.total_steps > 0 ? Math.round((job.completed_steps / job.total_steps) * 100) : 0;

  return (
    <div className="page">
      <div className="page-inner" style={{ maxWidth: 900 }}>
      <h2 className="page-title" style={{ marginTop: 0 }}>Processing case</h2>
      {error && <p className="badge badge-error">{error}</p>}
      {!job && !error && <p className="muted">Loading job status…</p>}

      {job && (
        <>
          <div className="card" style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <strong>
                Job {job.status} — {job.completed_steps}/{job.total_steps} steps
              </strong>
              <span className="muted">{pct}%</span>
            </div>
            <div className="progress-bar">
              <div style={{ width: `${pct}%` }} />
            </div>
            {job.status === "completed" && (
              <p style={{ marginTop: 14 }}>
                Done. <Link to={`/cases/${caseId ?? job.case_id}`}>Open case →</Link>
              </p>
            )}
            {job.status === "failed" && <p className="badge badge-error">Job failed: {job.error_message}</p>}
          </div>

          <div style={{ maxHeight: "60vh", overflow: "auto" }}>
            {job.steps.map((s) => (
              <div key={`${s.kind}-${s.name}`} className="timeline-row" style={{ gridTemplateColumns: "1fr 100px 90px" }}>
                <span className="mono">
                  {s.kind === "analyser" ? "▸ " : ""}
                  {s.name}
                </span>
                <span className="muted">
                  {s.num_events} ev{s.num_errors ? `, ${s.num_errors} err` : ""}
                </span>
                <StatusBadge status={s.status} />
              </div>
            ))}
          </div>
        </>
      )}
      </div>
    </div>
  );
}
