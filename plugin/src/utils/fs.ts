import { sha256Bytes } from './hash';

function encodePath(path: string): string {
  if (path.startsWith('file:')) {
    return path;
  }
  let normalized = path;
  if (normalized.match(/^[A-Za-z]:\\/)) {
    normalized = normalized.replace(/\\/g, '/');
    return `file:///${encodeURI(normalized)}`;
  }
  return `file://${encodeURI(normalized)}`;
}

export async function getEntryFromPath(path: string) {
  const { storage } = require('uxp');
  const fs = storage.localFileSystem;
  const url = encodePath(path);
  return fs.getEntryWithUrl(url);
}

export async function readFileBytes(entry: any): Promise<Uint8Array> {
  const buffer = await entry.read({ format: 'binary' });
  if (buffer instanceof ArrayBuffer) {
    return new Uint8Array(buffer);
  }
  if (buffer instanceof Uint8Array) {
    return buffer;
  }
  return new Uint8Array(buffer.buffer);
}

export async function getFileMetadata(entry: any) {
  const meta = await entry.getMetadata();
  return {
    size: meta.size || 0,
    modified: meta.dateModified ? new Date(meta.dateModified).toISOString() : new Date().toISOString()
  };
}

export async function hashFile(entry: any): Promise<string> {
  const bytes = await readFileBytes(entry);
  return sha256Bytes(bytes);
}

export async function ensureOutputFolder(outputDirUrl: string) {
  const { storage } = require('uxp');
  const fs = storage.localFileSystem;
  if (!outputDirUrl) {
    return fs.getFolder();
  }
  try {
    return await fs.getEntryWithUrl(outputDirUrl);
  } catch (err) {
    return fs.getFolder();
  }
}

export async function writeFileToFolder(folder: any, filename: string, data: Uint8Array) {
  const file = await folder.createFile(filename, { overwrite: true });
  await file.write(data.buffer, { format: 'binary' });
  return file;
}
