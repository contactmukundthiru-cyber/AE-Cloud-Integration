import { Zip, strToU8 } from 'fflate';
import { Manifest } from '../types';

export function stableStringify(value: any): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    const entries = keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value);
}

export interface ZipEntry {
  path: string;
  data: Uint8Array;
}

export async function createBundleZip(entries: ZipEntry[], manifest: Manifest): Promise<Uint8Array> {
  const chunks: Uint8Array[] = [];
  let done = false;
  const zip = new Zip((err, data, final) => {
    if (err) {
      throw err;
    }
    if (data) {
      chunks.push(data);
    }
    if (final) {
      done = true;
    }
  });

  const manifestJson = stableStringify(manifest);
  zip.add('manifest.json', strToU8(manifestJson), { level: 9, mtime: new Date(0) });

  entries.sort((a, b) => a.path.localeCompare(b.path));
  for (const entry of entries) {
    zip.add(entry.path, entry.data, { level: 9, mtime: new Date(0) });
  }

  zip.end();

  while (!done) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const output = new Uint8Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}
