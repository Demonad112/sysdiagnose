const API_BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface CaseSummary {
  id: string;
  display_name: string;
  status: "pending" | "processing" | "ready" | "error";
  ios_version: string | null;
  model: string | null;
  serial_number: string | null;
  created_at: string;
}

export interface JobStep {
  kind: string;
  name: string;
  status: string;
  num_events: number;
  num_errors: number;
  num_warnings: number;
  duration: number | null;
}

export interface JobStatus {
  job_id: string;
  case_id: string;
  status: "queued" | "running" | "completed" | "failed";
  total_steps: number;
  completed_steps: number;
  error_message: string | null;
  steps: JobStep[];
}

export interface ModuleMeta {
  kind: "parser" | "analyser";
  description: string;
  format: string;
  is_timeline: boolean;
  category: string;
}

export interface CategoryModule extends ModuleMeta {
  name: string;
  status: string;
  num_events: number;
  num_errors: number;
  num_warnings: number;
}

export interface CaseOverview {
  case: { id: string; display_name: string; status: string };
  categories: { id: string; label: string; modules: CategoryModule[] }[];
  unparsed_count: number;
}

export const api = {
  listCases: () => req<CaseSummary[]>("/cases"),
  getCase: (caseId: string) => req<CaseSummary & { latest_job_id: string | null }>(`/cases/${caseId}`),
  getOverview: (caseId: string) => req<CaseOverview>(`/cases/${caseId}/overview`),
  getUnparsed: (caseId: string) => req<{ path: string; size: number | null }[]>(`/cases/${caseId}/unparsed`),
  getParserOutput: (caseId: string, name: string) =>
    req<{ name: string; meta: ModuleMeta; data: unknown }>(`/cases/${caseId}/parsers/${name}`),
  search: (caseId: string, q: string) =>
    req<{ query: string; results: { parser: string; category: string; record: unknown }[] }>(
      `/cases/${caseId}/search?q=${encodeURIComponent(q)}`,
    ),
  deleteCase: (caseId: string) => req<{ deleted: string }>(`/cases/${caseId}`, { method: "DELETE" }),
  getJob: (jobId: string) => req<JobStatus>(`/jobs/${jobId}`),
  getLatestJob: (caseId: string) => req<JobStatus>(`/cases/${caseId}/jobs/latest`),

  createBatch: (mode: "archive" | "folder") =>
    req<{ batch_id: string; chunk_size: number }>("/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }),
  registerItem: (batchId: string, relativePath: string, size: number) =>
    req<{ item_id: string; total_chunks: number; chunk_size: number; received_chunks: number[] }>(
      `/uploads/${batchId}/items`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ relative_path: relativePath, size }),
      },
    ),
  itemStatus: (batchId: string, itemId: string) =>
    req<{ item_id: string; status: string; total_chunks: number; received_chunks: number[] }>(
      `/uploads/${batchId}/items/${itemId}/status`,
    ),
  uploadChunk: (batchId: string, itemId: string, chunkIndex: number, blob: Blob) =>
    req<{ received: number }>(`/uploads/${batchId}/items/${itemId}/chunks/${chunkIndex}`, {
      method: "PUT",
      body: blob,
    }),
  completeItem: (batchId: string, itemId: string) =>
    req<{ item_id: string; status: string }>(`/uploads/${batchId}/items/${itemId}/complete`, { method: "POST" }),
  completeBatch: (batchId: string) =>
    req<{ batch_id: string; case_id: string; job_id: string }>(`/uploads/${batchId}/complete`, { method: "POST" }),
};
