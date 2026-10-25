export interface SteamScreensaverService {
  GetActiveState(request?: Record<string, never>): unknown;
  ForceScreensaver?(request: unknown): unknown;
  RegisterForNotifyActiveStateChanged?(callback: (state: unknown) => void): unknown;
  RegisterForActiveStateChanged?(callback: (state: unknown) => void): unknown;
  RegisterForActiveStateChange?(callback: (state: unknown) => void): unknown;
  RegisterForActiveStateChanges?(callback: (state: unknown) => void): unknown;
}

export type SteamScreensaverRegistration = {
  unregister?: () => void;
  Unregister?: () => void;
} | undefined;

export function isSteamScreensaverService(value: unknown): value is SteamScreensaverService {
  const candidate = value as Partial<SteamScreensaverService> | null | undefined;
  return Boolean(
    candidate
    && typeof candidate.GetActiveState === "function"
  );
}

export function registerForScreensaverState(
  service: SteamScreensaverService,
  callback: (state: unknown) => void,
): SteamScreensaverRegistration {
  for (const name of [
    "RegisterForNotifyActiveStateChanged",
    "RegisterForActiveStateChanged",
    "RegisterForActiveStateChange",
    "RegisterForActiveStateChanges",
  ] as const) {
    const register = service[name];
    if (typeof register !== "function") continue;
    try {
      return register.call(service, callback) as SteamScreensaverRegistration;
    } catch {
      // Polling remains available when this Steam build exposes an incompatible
      // notification signature.
    }
  }
  return undefined;
}

function bodyOf(response: any): any {
  try {
    if (typeof response?.Body === "function") return response.Body();
  } catch {
    return null;
  }
  return response?.body ?? response?.response ?? response;
}

export function screensaverActiveFromResponse(response: unknown): boolean | null {
  const body = bodyOf(response);
  if (typeof body === "boolean") return body;
  if (body === 0 || body === 1) return Boolean(body);
  for (const key of ["active", "bActive", "is_active", "isActive"]) {
    let value = body?.[key];
    try {
      if (typeof value === "function") value = value.call(body);
    } catch {
      return null;
    }
    if (typeof value === "boolean") return value;
    if (value === 0 || value === 1) return Boolean(value);
  }
  return null;
}
