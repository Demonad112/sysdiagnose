import { useSyncExternalStore } from "react";

import { uploadManager } from "./uploadManager";

/** Subscribes a component to the upload manager's snapshot without owning any of its
 * state — a remount here (route change, StrictMode double-render, etc.) never resets
 * upload progress, it just re-subscribes to the same running manager. */
export function useUploadState() {
  return useSyncExternalStore(uploadManager.subscribe, uploadManager.getSnapshot);
}
