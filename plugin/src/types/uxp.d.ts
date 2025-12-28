// Adobe UXP Module Type Definitions

declare module 'uxp' {
  export namespace storage {
    export interface Entry {
      name: string;
      isFile: boolean;
      isFolder: boolean;
      nativePath: string;
    }

    export interface File extends Entry {
      isFile: true;
      read(options?: { format?: string }): Promise<string | ArrayBuffer>;
      write(data: string | ArrayBuffer, options?: { format?: string; append?: boolean }): Promise<void>;
      delete(): Promise<void>;
    }

    export interface Folder extends Entry {
      isFolder: true;
      getEntries(): Promise<Entry[]>;
      createFile(name: string, options?: { overwrite?: boolean }): Promise<File>;
      createFolder(name: string): Promise<Folder>;
      getEntry(path: string): Promise<Entry>;
      delete(): Promise<void>;
    }

    export interface FileSystemProvider {
      isFileSystemProvider: true;
    }

    export const localFileSystem: {
      getFileForOpening(options?: {
        types?: string[];
        initialDomain?: symbol;
        initialLocation?: Entry;
        allowMultiple?: boolean;
      }): Promise<File | File[] | null>;

      getFileForSaving(suggestedName: string, options?: {
        types?: string[];
        initialDomain?: symbol;
        initialLocation?: Entry;
      }): Promise<File | null>;

      getFolder(options?: {
        initialDomain?: symbol;
        initialLocation?: Entry;
      }): Promise<Folder | null>;

      getTemporaryFolder(): Promise<Folder>;
      getDataFolder(): Promise<Folder>;
      getPluginFolder(): Promise<Folder>;

      createEntryWithUrl(url: string, options?: { overwrite?: boolean }): Promise<Entry>;
      getEntryWithUrl(url: string): Promise<Entry>;

      getNativePath(entry: Entry): string;

      domains: {
        userDesktop: symbol;
        userDocuments: symbol;
        userPictures: symbol;
        userVideos: symbol;
        userMusic: symbol;
        userDownloads: symbol;
        appLocalData: symbol;
        appLocalCache: symbol;
        appLocalLibrary: symbol;
        appLocalSharedData: symbol;
        appRoamingData: symbol;
        appRoamingLibrary: symbol;
      };

      formats: {
        utf8: symbol;
        binary: symbol;
      };

      modes: {
        readOnly: symbol;
        readWrite: symbol;
      };

      types: {
        file: symbol;
        folder: symbol;
      };
    };

    export const secureStorage: {
      getItem(key: string): Promise<string | null>;
      setItem(key: string, value: string): Promise<void>;
      removeItem(key: string): Promise<void>;
      keys(): Promise<string[]>;
      length(): Promise<number>;
      clear(): Promise<void>;
    };
  }

  export namespace network {
    export interface FetchResponse {
      ok: boolean;
      status: number;
      statusText: string;
      headers: Headers;
      body: ReadableStream | null;
      json(): Promise<any>;
      text(): Promise<string>;
      arrayBuffer(): Promise<ArrayBuffer>;
      blob(): Promise<Blob>;
    }

    export function fetch(url: string, options?: {
      method?: string;
      headers?: Record<string, string>;
      body?: string | ArrayBuffer | FormData;
      credentials?: 'omit' | 'same-origin' | 'include';
    }): Promise<FetchResponse>;

    export class WebSocket {
      constructor(url: string, protocols?: string | string[]);

      readonly readyState: number;
      readonly bufferedAmount: number;
      readonly extensions: string;
      readonly protocol: string;

      binaryType: 'blob' | 'arraybuffer';

      onopen: ((event: Event) => void) | null;
      onclose: ((event: CloseEvent) => void) | null;
      onerror: ((event: Event) => void) | null;
      onmessage: ((event: MessageEvent) => void) | null;

      send(data: string | ArrayBuffer | Blob): void;
      close(code?: number, reason?: string): void;

      static readonly CONNECTING: 0;
      static readonly OPEN: 1;
      static readonly CLOSING: 2;
      static readonly CLOSED: 3;
    }
  }

  export namespace shell {
    export function openExternal(url: string): Promise<void>;
    export function openPath(path: string): Promise<string>;
  }

  export namespace os {
    export function platform(): string;
    export function release(): string;
    export function arch(): string;
    export function cpus(): { model: string; speed: number }[];
    export function totalmem(): number;
    export function freemem(): number;
    export function homedir(): string;
    export function tmpdir(): string;
  }

  export namespace entrypoints {
    export function setup(options: {
      panels?: Record<string, {
        create?: () => void;
        show?: () => void;
        hide?: () => void;
        destroy?: () => void;
        invokeMenu?: (id: string) => void;
        menuItems?: Array<{
          id: string;
          label: string;
          enabled?: boolean;
          checked?: boolean;
        }>;
      }>;
      commands?: Record<string, {
        run?: (...args: any[]) => void | Promise<void>;
      }>;
    }): void;
  }

  export const versions: {
    uxp: string;
    v8: string;
    host: string;
    hostOS: string;
    hostArch: string;
  };

  export const host: {
    name: string;
    version: string;
    uiLocale: string;
  };
}

export {};
