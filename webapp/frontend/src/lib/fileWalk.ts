export interface PickedFile {
  file: File;
  relativePath: string;
}

/** Turns a FileList from an <input type="file" webkitdirectory> or a plain multi-file
 * picker into {file, relativePath} pairs. webkitRelativePath is populated by the browser
 * for directory picks; for plain file picks we fall back to just the filename. */
export function filesFromFileList(list: FileList): PickedFile[] {
  return Array.from(list).map((file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
}

/** Recursively walks a DataTransferItemList from a drop event, resolving both loose
 * files and whole dropped folders into {file, relativePath} pairs via the (non-standard
 * but universally supported) webkitGetAsEntry API. */
export async function filesFromDataTransfer(items: DataTransferItemList): Promise<PickedFile[]> {
  const entries: FileSystemEntry[] = [];
  for (const item of Array.from(items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  const results: PickedFile[] = [];
  await Promise.all(entries.map((entry) => walkEntry(entry, "", results)));
  return results;
}

async function walkEntry(entry: FileSystemEntry, prefix: string, out: PickedFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    out.push({ file, relativePath: prefix + entry.name });
    return;
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const children = await readAllEntries(reader);
    await Promise.all(children.map((child) => walkEntry(child, `${prefix}${entry.name}/`, out)));
  }
}

function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  // readEntries() only returns a batch at a time per the spec; must call until empty.
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = [];
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(all);
          return;
        }
        all.push(...batch);
        readBatch();
      }, reject);
    };
    readBatch();
  });
}
