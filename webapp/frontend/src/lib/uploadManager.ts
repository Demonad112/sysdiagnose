/**
 * Upload state lives here, in a plain module-level object outside React's tree —
 * not in a component's useState/useReducer. This is the actual fix for the prototype's
 * "folder + files together sometimes wipes all progress" bug: when upload progress is
 * tied to a component's state, any full re-render/remount of that component (route
 * change, an unrelated error boundary trip, React key churn from mixing two file
 * inputs) throws the in-flight upload state away with it. Here the manager keeps running
 * regardless of what the component tree does; React components just subscribe to a
 * snapshot via useSyncExternalStore and can mount/unmount freely without affecting it.
 *
 * Resumability: every chunk send updates localStorage with {relativePath, size,
 * lastModified, itemId, sentChunks}. If the tab is hard-refreshed mid-upload, re-picking
 * the same folder/files lets the manager match items by (relativePath, size,
 * lastModified), ask the server which chunks it already has (GET item status), and only
 * send what's missing — instead of restarting a 400MB archive from byte 0.
 */

import { api } from "./api";

export type UploadFileStatus = "queued" | "uploading" | "assembling" | "done" | "error";

export interface ManagedItem {
  relativePath: string;
  size: number;
  lastModified: number;
  file: File;
  itemId: string | null;
  totalChunks: number;
  chunkSize: number;
  sentChunks: number[];
  status: UploadFileStatus;
  error?: string;
}

export type BatchStatus = "idle" | "uploading" | "completing" | "done" | "error";

export interface ManagedBatch {
  batchId: string | null;
  mode: "archive" | "folder";
  items: ManagedItem[];
  status: BatchStatus;
  caseId?: string;
  jobId?: string;
  error?: string;
}

interface PersistedItem {
  relativePath: string;
  size: number;
  lastModified: number;
  itemId: string | null;
  totalChunks: number;
  chunkSize: number;
  sentChunks: number[];
}

interface PersistedBatch {
  batchId: string | null;
  mode: "archive" | "folder";
  items: PersistedItem[];
}

const STORAGE_KEY = "sysdx.upload.batch.v1";

function loadPersisted(): PersistedBatch | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedBatch) : null;
  } catch {
    return null;
  }
}

function persist(batch: ManagedBatch | null) {
  if (!batch) {
    localStorage.removeItem(STORAGE_KEY);
    return;
  }
  const payload: PersistedBatch = {
    batchId: batch.batchId,
    mode: batch.mode,
    items: batch.items.map((i) => ({
      relativePath: i.relativePath,
      size: i.size,
      lastModified: i.lastModified,
      itemId: i.itemId,
      totalChunks: i.totalChunks,
      chunkSize: i.chunkSize,
      sentChunks: i.sentChunks,
    })),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

class UploadManager {
  private batch: ManagedBatch | null = null;
  private listeners = new Set<() => void>();

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  };

  getSnapshot = (): ManagedBatch | null => this.batch;

  /** Any previously in-progress batch found in localStorage (e.g. after a hard refresh). */
  getResumableInfo(): { mode: "archive" | "folder"; fileCount: number } | null {
    const persisted = loadPersisted();
    if (!persisted || persisted.items.every((i) => i.sentChunks.length >= i.totalChunks)) return null;
    return { mode: persisted.mode, fileCount: persisted.items.length };
  }

  discardResumable() {
    localStorage.removeItem(STORAGE_KEY);
  }

  private notify() {
    if (this.batch) this.batch = { ...this.batch, items: [...this.batch.items] };
    persist(this.batch);
    this.listeners.forEach((l) => l());
  }

  private patchItem(relativePath: string, patch: Partial<ManagedItem>) {
    if (!this.batch) return;
    const idx = this.batch.items.findIndex((i) => i.relativePath === relativePath);
    if (idx === -1) return;
    this.batch.items[idx] = { ...this.batch.items[idx], ...patch };
    this.notify();
  }

  /** Starts a new batch, or reuses/extends the current one if it's the same mode — this
   * is what lets a folder drop and a follow-up individual-file pick merge into one
   * upload instead of clobbering each other. */
  addFiles(files: { file: File; relativePath: string }[], mode: "archive" | "folder") {
    if (!this.batch || this.batch.mode !== mode || this.batch.status === "done") {
      const persisted = loadPersisted();
      const reuse = persisted && persisted.mode === mode ? persisted : null;
      this.batch = {
        batchId: reuse?.batchId ?? null,
        mode,
        items: [],
        status: "idle",
      };
    }

    const persisted = loadPersisted();
    for (const { file, relativePath } of files) {
      if (this.batch.items.some((i) => i.relativePath === relativePath)) continue;
      const match = persisted?.items.find(
        (i) => i.relativePath === relativePath && i.size === file.size && i.lastModified === file.lastModified,
      );
      this.batch.items.push({
        relativePath,
        size: file.size,
        lastModified: file.lastModified,
        file,
        itemId: match?.itemId ?? null,
        totalChunks: match?.totalChunks ?? 0,
        chunkSize: match?.chunkSize ?? 0,
        sentChunks: match?.sentChunks ?? [],
        status: "queued",
      });
    }
    this.notify();
  }

  removeItem(relativePath: string) {
    if (!this.batch) return;
    this.batch.items = this.batch.items.filter((i) => i.relativePath !== relativePath);
    this.notify();
  }

  reset() {
    this.batch = null;
    this.discardResumable();
    this.listeners.forEach((l) => l());
  }

  async start(): Promise<{ caseId: string; jobId: string }> {
    if (!this.batch) throw new Error("No files added");
    this.batch.status = "uploading";
    this.notify();

    try {
      if (!this.batch.batchId) {
        const created = await api.createBatch(this.batch.mode);
        this.batch.batchId = created.batch_id;
        this.notify();
      }
      const batchId = this.batch.batchId;

      // sequential is deliberate: keeps memory/network predictable for very large
      // archives instead of firing dozens of concurrent multi-MB chunk requests
      for (const item of [...this.batch.items]) {
        await this.uploadItem(batchId, item.relativePath);
      }

      this.batch.status = "completing";
      this.notify();
      const result = await api.completeBatch(batchId);
      this.batch.status = "done";
      this.batch.caseId = result.case_id;
      this.batch.jobId = result.job_id;
      this.notify();
      this.discardResumable();
      return { caseId: result.case_id, jobId: result.job_id };
    } catch (e) {
      if (this.batch) {
        this.batch.status = "error";
        this.batch.error = e instanceof Error ? e.message : String(e);
        this.notify();
      }
      throw e;
    }
  }

  private async uploadItem(batchId: string, relativePath: string) {
    const item = this.batch?.items.find((i) => i.relativePath === relativePath);
    if (!item) return;
    this.patchItem(relativePath, { status: "uploading" });

    if (!item.itemId) {
      const registered = await api.registerItem(batchId, relativePath, item.size);
      this.patchItem(relativePath, {
        itemId: registered.item_id,
        totalChunks: registered.total_chunks,
        chunkSize: registered.chunk_size,
        sentChunks: [],
      });
    } else {
      // resuming: confirm with the server what it actually has (don't just trust localStorage)
      try {
        const status = await api.itemStatus(batchId, item.itemId);
        if (status.status === "assembled") {
          this.patchItem(relativePath, { status: "done", sentChunks: [] });
          return;
        }
        this.patchItem(relativePath, { sentChunks: status.received_chunks });
      } catch {
        // item unknown to this server (e.g. fresh backend) — re-register from scratch
        const registered = await api.registerItem(batchId, relativePath, item.size);
        this.patchItem(relativePath, {
          itemId: registered.item_id,
          totalChunks: registered.total_chunks,
          chunkSize: registered.chunk_size,
          sentChunks: [],
        });
      }
    }

    const current = this.batch!.items.find((i) => i.relativePath === relativePath)!;
    const sent = new Set(current.sentChunks);
    for (let idx = 0; idx < current.totalChunks; idx++) {
      if (sent.has(idx)) continue;
      const start = idx * current.chunkSize;
      const blob = current.file.slice(start, start + current.chunkSize);
      await api.uploadChunk(batchId, current.itemId!, idx, blob);
      sent.add(idx);
      this.patchItem(relativePath, { sentChunks: [...sent] });
    }

    this.patchItem(relativePath, { status: "assembling" });
    await api.completeItem(batchId, current.itemId!);
    this.patchItem(relativePath, { status: "done" });
  }
}

export const uploadManager = new UploadManager();
