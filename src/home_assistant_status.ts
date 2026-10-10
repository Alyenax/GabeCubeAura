// The Home Assistant page's connection line, step by step. Kept free of Decky imports so it is tested.

export type ConnectionPhase = "off" | "connecting" | "connected" | "waiting_retry";

// The fields of the bridge's status() that describe the connection (signalbar/mqtt/bridge.py).
export interface ConnectionStatus {
  phase: ConnectionPhase;
  // Why the last attempt failed, in plain English; "" while connected or before any failure.
  reason: string;
  // Seconds until the next attempt while waiting after a failure, else null.
  retry_in_s: number | null;
  broker: string;
  username: string;
  topic_root: string;
}

/** secondsSinceStatus: how long ago the status arrived, so the countdown keeps running between polls. */
export function connectionLine(enabled: boolean, status: ConnectionStatus, secondsSinceStatus = 0): string {
  if (!enabled || status.phase === "off") return "Off";
  if (status.phase === "connected") {
    return `Connected as ${status.username || "anonymous"}, publishing under ${status.topic_root}`;
  }
  if (status.phase === "waiting_retry") {
    const reason = status.reason || "Not connected";
    const left = Math.max(0, Math.ceil((status.retry_in_s ?? 0) - secondsSinceStatus));
    return left > 0 ? `${reason}, retrying in ${left} s` : `${reason}, retrying now…`;
  }
  const attempt = `Connecting to ${status.broker}…`;
  return status.reason ? `${attempt} Last attempt: ${status.reason}.` : attempt;
}
