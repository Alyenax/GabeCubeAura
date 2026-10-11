// The connection line on the Home Assistant page. No Decky imports, so it can be unit tested.

export type ConnectionPhase = "off" | "connecting" | "connected" | "waiting_retry";

export interface ConnectionStatus {
  phase: ConnectionPhase;
  // Why the last attempt failed; "" while connected or before the first failure.
  reason: string;
  retry_in_s: number | null;
  broker: string;
  username: string;
  topic_root: string;
}

/** secondsSinceStatus keeps the retry countdown running between polls. */
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
