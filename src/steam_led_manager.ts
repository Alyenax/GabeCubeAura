export const STEAM_LED_MODE_IDLE = 2;
export const STEAM_LED_MODE_DOWNLOAD = 3;
export const STEAM_LED_MODE_CUSTOMIZE = 4;

export interface SteamLEDModeOverrideService {
  RequestModeOverride(mode: number, debugString: string): (() => void) | void;
}

export interface SteamLEDManagerTransport {
  GetState(request?: Record<string, never>): unknown;
  SetManagerMode(request: { mode: number }): unknown;
}

export type SteamDownloadOverrideState = "blocked" | "download" | "inactive" | "unavailable" | "error";

const SAFETY_RELEASE_KEY = "__gabecubeAuraSteamSafetyRelease";

type SafetyReleaseGlobal = typeof globalThis & {
  [SAFETY_RELEASE_KEY]?: () => void;
};

function releaseRememberedSafetyOverride(): void {
  const owner = globalThis as SafetyReleaseGlobal;
  const release = owner[SAFETY_RELEASE_KEY];
  delete owner[SAFETY_RELEASE_KEY];
  if (release) release();
}

export function isSteamLEDModeOverrideService(
  value: unknown,
): value is SteamLEDModeOverrideService {
  const candidate = value as Partial<SteamLEDModeOverrideService> | null | undefined;
  return Boolean(candidate && typeof candidate.RequestModeOverride === "function");
}

export function isSteamLEDManagerTransport(
  value: unknown,
): value is SteamLEDManagerTransport {
  const candidate = value as Partial<SteamLEDManagerTransport> | null | undefined;
  return Boolean(
    candidate
    && typeof candidate.GetState === "function"
    && typeof candidate.SetManagerMode === "function"
  );
}

function responseSucceeded(response: unknown): boolean {
  const candidate = response as { BSuccess?: () => boolean } | null | undefined;
  try {
    return typeof candidate?.BSuccess !== "function" || Boolean(candidate.BSuccess());
  } catch {
    return false;
  }
}

/**
 * Safety only uses Steam's reversible Customize override because it must keep
 * Download mode suppressed. Downloads + safety deliberately does not hold an
 * override: once the backend has restored the native hardware state it asks
 * the LED manager for Download directly. This avoids leaving an uncallable
 * override on Steam's stack if Decky crashes.
 */
export class SteamDownloadLedOverride {
  private release: (() => void) | undefined;
  private overrideService: SteamLEDModeOverrideService | undefined;
  private transport: SteamLEDManagerTransport | undefined;
  private managerMode: number | undefined;

  constructor(
    private readonly discoverOverride: () => SteamLEDModeOverrideService | undefined,
    private readonly discoverTransport: () => SteamLEDManagerTransport | undefined,
  ) {}

  async recoverAfterRestart(): Promise<SteamDownloadOverrideState> {
    try {
      releaseRememberedSafetyOverride();
      this.transport ??= this.discoverTransport();
      if (!this.transport) return "unavailable";
      await this.setManagerMode(STEAM_LED_MODE_IDLE);
      return "inactive";
    } catch {
      this.releaseSafetyOverride();
      return "error";
    }
  }

  async update(
    suppressDownload: boolean,
    restoreDownload: boolean,
  ): Promise<SteamDownloadOverrideState> {
    try {
      if (suppressDownload) {
        this.transport ??= this.discoverTransport();
        this.overrideService ??= this.discoverOverride();
        if (!this.transport || !this.overrideService) return "unavailable";
        if (!this.release) {
          releaseRememberedSafetyOverride();
          const rawRelease = this.overrideService.RequestModeOverride(
            STEAM_LED_MODE_CUSTOMIZE,
            "GabeCubeAura protected ownership",
          );
          if (typeof rawRelease !== "function") return "unavailable";
          const owner = globalThis as SafetyReleaseGlobal;
          let released = false;
          const trackedRelease = () => {
            if (released) return;
            released = true;
            if (owner[SAFETY_RELEASE_KEY] === trackedRelease) {
              delete owner[SAFETY_RELEASE_KEY];
            }
            rawRelease();
          };
          owner[SAFETY_RELEASE_KEY] = trackedRelease;
          this.release = trackedRelease;
        }
        await this.setManagerMode(STEAM_LED_MODE_CUSTOMIZE, true);
        return "blocked";
      }

      this.releaseSafetyOverride();
      if (restoreDownload) {
        this.transport ??= this.discoverTransport();
        if (!this.transport) return "unavailable";
        await this.setManagerMode(STEAM_LED_MODE_DOWNLOAD);
        return "download";
      }

      if (this.managerMode === STEAM_LED_MODE_DOWNLOAD) {
        await this.setManagerMode(STEAM_LED_MODE_IDLE);
      }
      return "inactive";
    } catch {
      this.releaseSafetyOverride();
      return "error";
    }
  }

  stop(): void {
    this.releaseSafetyOverride();
    if (this.managerMode === STEAM_LED_MODE_DOWNLOAD && this.transport) {
      const transport = this.transport;
      this.managerMode = undefined;
      void Promise.resolve(transport.SetManagerMode({ mode: STEAM_LED_MODE_IDLE }))
        .catch(() => undefined);
    }
  }

  private releaseSafetyOverride(): void {
    const release = this.release;
    this.release = undefined;
    if (!release) return;
    try {
      release();
    } catch {
      // Steam may already be tearing down its UI transport. The globally
      // remembered release is cleared before the private callback is invoked.
    }
  }

  private async setManagerMode(mode: number, reassert = false): Promise<void> {
    if (!this.transport) throw new Error("Steam LED manager transport unavailable");
    if (!reassert && this.managerMode === mode) return;
    const response = await Promise.resolve(this.transport.SetManagerMode({ mode }));
    if (!responseSucceeded(response)) {
      throw new Error(`Steam LED manager rejected mode ${mode}`);
    }
    this.managerMode = mode;
  }
}
