const LABELS: Record<string, string> = {
  ok: "ok",
  success: "ok",
  warning: "warning",
  error: "error",
  skipped: "skipped",
  pending: "pending",
  running: "running",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = ["ok", "success"].includes(status)
    ? "badge-ok"
    : status === "warning"
      ? "badge-warning"
      : status === "error"
        ? "badge-error"
        : "badge-skipped";
  return <span className={`badge ${cls}`}>{LABELS[status] ?? status}</span>;
}
