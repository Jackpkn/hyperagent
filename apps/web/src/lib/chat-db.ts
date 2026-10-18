import type { Chat } from "./chat-model";
import type { Frame } from "./protocol";

// Chats, their step screenshots and small settings live in the browser's IndexedDB: localStorage caps
// out near 5 MB and a single run's screenshots can exceed that. If IndexedDB is unavailable (private
// windows, blocked site data) everything falls back to memory and `persistent` reports false.

const DB_NAME = "hyperagent";
const DB_VERSION = 1;
const CHATS = "chats";
const FRAMES = "frames";
const KV = "kv";

type StoreName = typeof CHATS | typeof FRAMES | typeof KV;

let dbPromise: Promise<IDBDatabase | null> | null = null;
const memory: Record<StoreName, Map<string, unknown>> = {
  [CHATS]: new Map(),
  [FRAMES]: new Map(),
  [KV]: new Map(),
};

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(CHATS)) db.createObjectStore(CHATS, { keyPath: "id" });
        if (!db.objectStoreNames.contains(FRAMES)) db.createObjectStore(FRAMES);
        if (!db.objectStoreNames.contains(KV)) db.createObjectStore(KV);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

export async function isPersistent(): Promise<boolean> {
  return (await openDb()) !== null;
}

function run<T>(
  store: StoreName,
  mode: IDBTransactionMode,
  op: (s: IDBObjectStore) => IDBRequest<T> | void,
): Promise<T | undefined> {
  return openDb().then(
    (db) =>
      new Promise<T | undefined>((resolve, reject) => {
        if (!db) return resolve(undefined);
        const tx = db.transaction(store, mode);
        const request = op(tx.objectStore(store));
        tx.oncomplete = () => resolve(request ? request.result : undefined);
        tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
        tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
      }),
  );
}

export async function listChats(): Promise<Chat[]> {
  const db = await openDb();
  const chats = db
    ? ((await run<Chat[]>(CHATS, "readonly", (s) => s.getAll() as IDBRequest<Chat[]>)) ?? [])
    : ([...memory[CHATS].values()] as Chat[]);
  return [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function putChat(chat: Chat): Promise<void> {
  if (!(await openDb())) {
    memory[CHATS].set(chat.id, chat);
    return;
  }
  await run(CHATS, "readwrite", (s) => s.put(chat));
}

const framePrefix = (chatId: string) => `${chatId}/`;

export async function deleteChat(chatId: string): Promise<void> {
  if (!(await openDb())) {
    memory[CHATS].delete(chatId);
    for (const key of [...memory[FRAMES].keys()]) if (key.startsWith(framePrefix(chatId))) memory[FRAMES].delete(key);
    return;
  }
  await run(CHATS, "readwrite", (s) => s.delete(chatId));
  const prefix = framePrefix(chatId);
  await run(FRAMES, "readwrite", (s) => s.delete(IDBKeyRange.bound(prefix, `${prefix}￿`)));
}

export async function putFrame(chatId: string, key: string, frame: Frame): Promise<void> {
  const id = framePrefix(chatId) + key;
  if (!(await openDb())) {
    memory[FRAMES].set(id, frame);
    return;
  }
  await run(FRAMES, "readwrite", (s) => s.put(frame, id));
}

export async function getFrame(chatId: string, key: string): Promise<Frame | null> {
  const id = framePrefix(chatId) + key;
  if (!(await openDb())) return (memory[FRAMES].get(id) as Frame | undefined) ?? null;
  return ((await run<Frame>(FRAMES, "readonly", (s) => s.get(id) as IDBRequest<Frame>)) as Frame) ?? null;
}

export async function getSetting<T>(key: string): Promise<T | undefined> {
  if (!(await openDb())) return memory[KV].get(key) as T | undefined;
  return run<T>(KV, "readonly", (s) => s.get(key) as IDBRequest<T>);
}

export async function setSetting<T>(key: string, value: T): Promise<void> {
  if (!(await openDb())) {
    memory[KV].set(key, value);
    return;
  }
  await run(KV, "readwrite", (s) => s.put(value, key));
}
