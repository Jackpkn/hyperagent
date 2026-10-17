import type { Finding, RunResult, RunState } from "./protocol";

const PROFILE_STORAGE_KEY = "hyperagent.profile.v1";
const HISTORY_STORAGE_KEY = "hyperagent.history.v1";
const PERSIST_SESSION_KEY = "hyperagent.persist_session.v1";
const MAX_HISTORY_ITEMS = 20;

export interface OperatorProfile {
  enabled: boolean;
  name: string;
  email: string;
  phone: string;
  address: string;
  company: string;
  notes: string;
}

export const defaultOperatorProfile: OperatorProfile = {
  enabled: true,
  name: "",
  email: "",
  phone: "",
  address: "",
  company: "",
  notes: "",
};

export interface RunHistoryEntry {
  id: string;
  goal: string;
  createdAt: number;
  status: RunState;
  stepsCount: number;
  elapsedS: number;
  costUsd: number;
  findings: Finding[];
  result: RunResult | null;
}

export function loadOperatorProfile(): OperatorProfile {
  if (typeof window === "undefined") return defaultOperatorProfile;
  try {
    const raw = window.localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) return defaultOperatorProfile;
    const parsed = JSON.parse(raw) as Partial<OperatorProfile>;
    return {
      enabled: typeof parsed.enabled === "boolean" ? parsed.enabled : true,
      name: typeof parsed.name === "string" ? parsed.name : "",
      email: typeof parsed.email === "string" ? parsed.email : "",
      phone: typeof parsed.phone === "string" ? parsed.phone : "",
      address: typeof parsed.address === "string" ? parsed.address : "",
      company: typeof parsed.company === "string" ? parsed.company : "",
      notes: typeof parsed.notes === "string" ? parsed.notes : "",
    };
  } catch {
    return defaultOperatorProfile;
  }
}

export function saveOperatorProfile(profile: OperatorProfile): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  } catch {
    // Ignore storage quota errors
  }
}

export function hasOperatorProfileData(profile: OperatorProfile): boolean {
  return Boolean(
    profile.name.trim() ||
      profile.email.trim() ||
      profile.phone.trim() ||
      profile.address.trim() ||
      profile.company.trim() ||
      profile.notes.trim(),
  );
}

export function formatOperatorContext(profile: OperatorProfile): string {
  if (!profile.enabled || !hasOperatorProfileData(profile)) return "";
  const parts: string[] = [];
  if (profile.name.trim()) parts.push(`Name: ${profile.name.trim()}`);
  if (profile.email.trim()) parts.push(`Email: ${profile.email.trim()}`);
  if (profile.phone.trim()) parts.push(`Phone: ${profile.phone.trim()}`);
  if (profile.address.trim()) parts.push(`Address/Location: ${profile.address.trim()}`);
  if (profile.company.trim()) parts.push(`Company/Role: ${profile.company.trim()}`);
  if (profile.notes.trim()) parts.push(`Preferences/Notes: ${profile.notes.trim()}`);
  return parts.join(" | ");
}

export function loadPersistSession(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(PERSIST_SESSION_KEY) === "1";
  } catch {
    return false;
  }
}

export function savePersistSession(persist: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PERSIST_SESSION_KEY, persist ? "1" : "0");
  } catch {
    // Ignore storage errors
  }
}

export function loadRunHistory(): RunHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as RunHistoryEntry[]) : [];
  } catch {
    return [];
  }
}

export function upsertRunHistory(entry: RunHistoryEntry): RunHistoryEntry[] {
  const existing = loadRunHistory();
  const filtered = existing.filter((item) => item.id !== entry.id);
  const next = [entry, ...filtered].slice(0, MAX_HISTORY_ITEMS);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Ignore storage errors
    }
  }
  return next;
}

export function deleteRunHistoryItem(id: string): RunHistoryEntry[] {
  const next = loadRunHistory().filter((item) => item.id !== id);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Ignore storage errors
    }
  }
  return next;
}

export function clearRunHistory(): RunHistoryEntry[] {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(HISTORY_STORAGE_KEY);
    } catch {
      // Ignore storage errors
    }
  }
  return [];
}
