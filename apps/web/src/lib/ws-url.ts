// Resolves the agent WebSocket endpoint.
// NEXT_PUBLIC_WS_URL wins; otherwise same-origin under /ws/agent, except on the
// Next dev server (port 3000) where the Python service is assumed on 8766.
const AGENT_PATH = "/ws/agent";
const DEV_BACKEND = "ws://localhost:8766/ws/agent";

export function getWsUrl(): string {
  const override = process.env.NEXT_PUBLIC_WS_URL?.trim();
  if (override) return override;

  if (window.location.port === "3000") return DEV_BACKEND;

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${AGENT_PATH}`;
}
