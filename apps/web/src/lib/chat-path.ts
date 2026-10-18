export function chatPath(id: string | null): string {
  return id ? `/c/${encodeURIComponent(id)}` : "/";
}

export function chatIdFromPath(path: string): string | null {
  const match = /^\/c\/([A-Za-z0-9_-]+)\/?$/.exec(path);
  return match?.[1] ?? null;
}
