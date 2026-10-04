import { Router, findModuleExport } from "@decky/ui";

import {
  gameChanged,
  getArtwork,
  getStatus,
  reportParentalMinutes,
  reportRuntimeDiagnostic,
  setSteamActivity,
  submitArtwork,
  triggerEvent,
  updateControllers,
  resetControllers,
  reportControllerTelemetry,
  setScreenSyncContext,
} from "./api";
import { sampleArtwork } from "./artwork";
import { ControllerMonitor, isSteamInputService } from "./controller_monitor";
import { isSteamControllerStore } from "./controller_battery";
import type { SteamControllerStore } from "./controller_battery";
import { normalizeAppId } from "./steam_app_id";
import {
  downloadItemsActive,
  downloadOverviewActive,
  resolveDownloadActivity,
} from "./download_activity";
import { GameSessionLatch, selectObservedGame } from "./game_session";
import type { GameSessionDecision } from "./game_session";
import { ParentalPlaytimeSubscription } from "./parental_playtime";
import {
  isSteamScreensaverService,
  registerForScreensaverState,
  screensaverActiveFromResponse,
} from "./steam_screensaver";
import type {
  SteamScreensaverRegistration,
  SteamScreensaverService,
} from "./steam_screensaver";
import {
  classifySteamNotification,
  CommunityNotificationObserver,
  isSteamServerNotificationStore,
  screenshotWasCaptured,
} from "./steam_events";
import type { LightEvent, SteamServerNotificationStore } from "./steam_events";
import {
  isSteamLEDManagerTransport,
  isSteamLEDModeOverrideService,
  SteamDownloadLedOverride,
} from "./steam_led_manager";
import type { SteamDownloadOverrideState } from "./steam_led_manager";
import type { Status } from "./types";

declare const SteamClient: any;
declare const appStore: any;

type Registration = { unregister?: () => void } | undefined;

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function runningApp() {
  try {
    const main: any = Router?.MainRunningApp;
    return selectObservedGame(main, Router?.RunningApps);
  } catch {
    return { appid: 0, title: "" };
  }
}

function titleFor(appid: number): string {
  try {
    return String(appStore?.GetAppOverviewByAppID?.(appid)?.display_name ?? "");
  } catch {
    return "";
  }
}

class GabeCubeAuraRuntime {
  private alive = false;
  private desired = { appid: 0, title: "", source: "startup", launchSequence: 0 };
  private session = new GameSessionLatch();
  private baselineEstablished = false;
  private confirmedKey = "";
  private syncing = false;
  private artworkGeneration = 0;
  private parentalWaitStartedAt = 0;
  private pollTimer: number | undefined;
  private retryTimer: number | undefined;
  private gameRegistration: Registration;
  private downloadRegistration: Registration;
  private downloadItemsRegistration: Registration;
  private resumeRegistration: Registration;
  private parental = new ParentalPlaytimeSubscription(
    () => {
      const owner = SteamClient?.Parental;
      const register = owner?.RegisterForParentalPlaytimeWarnings;
      return typeof register === "function" ? { owner, register } : undefined;
    },
    (appid, minutes) => this.handleParentalMinutes(appid, minutes),
  );
  private notificationsRegistration: Registration;
  private screenshotRegistration: Registration;
  private communityNotificationsTimer: number | undefined;
  private communityNotificationStore: SteamServerNotificationStore | undefined;
  private communityNotificationObserver = new CommunityNotificationObserver();
  private lastNativeCommentAt = 0;
  private lastServerCommentAt = 0;
  private controllerMonitor: ControllerMonitor | undefined;
  private downloadActive = false;
  private downloadOverviewActive = false;
  private downloadItemsActive = false;
  private downloadItemsSeen = false;
  private downloadActivitySource = "startup-waiting";
  private steamActivitySyncing = false;
  private steamActivityDirty = false;
  private steamLedOverrideState: SteamDownloadOverrideState | "" = "";
  private downloadLedOverride = new SteamDownloadLedOverride(
    () => findModuleExport(isSteamLEDModeOverrideService),
    () => findModuleExport(isSteamLEDManagerTransport),
  );
  private steamLedRecovery: Promise<SteamDownloadOverrideState> = Promise.resolve("inactive");
  private screensaverService: SteamScreensaverService | undefined;
  private screensaverRegistration: SteamScreensaverRegistration;
  private screensaverRegistrationAttempted = false;
  private screensaverPolling = false;
  private screensaverFailures = 0;

  start() {
    if (this.alive) return;
    this.alive = true;
    this.steamLedRecovery = this.downloadLedOverride.recoverAfterRestart();
    this.applySessionDecision(this.session.seed(runningApp()));
    // Establish the observed AppID before lifetime notifications are attached.
    // Some Steam builds replay the currently running session immediately.
    this.baselineEstablished = true;
    this.registerSteamEvents();
    this.renewSteamActivity();
    this.pollTimer = window.setInterval(() => {
      this.observeRunningApp();
      this.renewSteamActivity();
      void this.pollScreensaver();
    }, 2000);
    void setScreenSyncContext("steam-screensaver", false, "waiting", "").catch(() => undefined);
    void this.pollScreensaver();
    console.log("[GabeCubeAura] background runtime started");
  }

  stop() {
    this.alive = false;
    if (this.pollTimer !== undefined) window.clearInterval(this.pollTimer);
    if (this.communityNotificationsTimer !== undefined) {
      window.clearInterval(this.communityNotificationsTimer);
      this.communityNotificationsTimer = undefined;
    }
    if (this.retryTimer !== undefined) window.clearTimeout(this.retryTimer);
    this.gameRegistration?.unregister?.();
    this.downloadRegistration?.unregister?.();
    this.downloadItemsRegistration?.unregister?.();
    this.resumeRegistration?.unregister?.();
    this.parental.stop();
    this.notificationsRegistration?.unregister?.();
    this.screenshotRegistration?.unregister?.();
    this.communityNotificationStore = undefined;
    this.communityNotificationObserver.reset();
    this.lastNativeCommentAt = 0;
    this.lastServerCommentAt = 0;
    this.downloadActive = false;
    this.downloadOverviewActive = false;
    this.downloadItemsActive = false;
    this.downloadItemsSeen = false;
    this.downloadActivitySource = "stopped";
    this.steamActivityDirty = false;
    this.downloadLedOverride.stop();
    this.steamLedOverrideState = "";
    this.unregisterScreensaverState();
    this.screensaverService = undefined;
    this.screensaverFailures = 0;
    void this.controllerMonitor?.stop().then(() => resetControllers()).catch(console.warn);
    void setSteamActivity(false, "").catch(() => undefined);
    void setScreenSyncContext("steam-screensaver", false, "waiting", "").catch(() => undefined);
    console.log("[GabeCubeAura] background runtime stopped");
  }

  private observeRunningApp() {
    this.applySessionDecision(this.session.observePoll(runningApp()));
    this.parental.ensure();
    void reportRuntimeDiagnostic(
      "heartbeat", this.desired.appid, "background runtime", 0,
    ).catch(() => undefined);
  }

  private applySessionDecision(decision: GameSessionDecision) {
    if (decision.action === "retain") {
      void reportRuntimeDiagnostic(
        "game_retained", decision.appid, decision.source, 0,
      ).catch(() => undefined);
      return;
    }
    if (decision.action === "update") {
      this.requestGame(
        decision.appid, decision.title, decision.source, decision.launch,
      );
    }
  }

  private requestGame(appid: number, title: string, source: string, launch = false) {
    if (!this.alive) return;
    const normalized = normalizeAppId(appid);
    const previousAppId = this.desired.appid;
    const changedApp = normalized !== previousAppId;
    const isLaunch = normalized > 0 && changedApp && this.baselineEstablished && Boolean(launch);
    const next = {
      appid: normalized,
      title: normalized > 0 ? String(title || "") : "",
      source: String(source || "unknown"),
      launchSequence: this.desired.launchSequence + (isLaunch ? 1 : 0),
    };
    this.desired = next;
    if (changedApp) {
      this.artworkGeneration += 1;
    }
    void this.flushGameState();
  }

  private async flushGameState() {
    if (this.syncing || !this.alive) return;
    this.syncing = true;
    try {
      while (this.alive) {
        const current = { ...this.desired };
        const key = `${current.appid}:${current.title}:${current.launchSequence}`;
        if (key === this.confirmedKey) break;
        try {
          const syncStartedAt = Date.now();
          const launch = current.launchSequence !== this.desired.launchSequence
            ? false : current.launchSequence > 0 && current.appid > 0;
          const status = await gameChanged(
            current.appid, current.title, launch, current.source,
          );
          const syncMs = Date.now() - syncStartedAt;
          this.confirmedKey = key;
          this.baselineEstablished = true;
          this.parentalWaitStartedAt = current.appid > 0 ? Date.now() : 0;
          void reportRuntimeDiagnostic(
            "game_synced", current.appid, current.source, syncMs,
          ).catch((error) => console.warn("[GabeCubeAura] runtime diagnostic failed", error));
          // Register only after the backend has accepted the new AppID. Some
          // Steam builds invoke this callback immediately on registration.
          this.parental.selectApp(current.appid);
          if (current.appid > 0) {
            const generation = this.artworkGeneration;
            void this.syncArtwork(current.appid, status, generation);
          }
        } catch (error) {
          console.warn("[GabeCubeAura] background game sync failed; retrying", error);
          this.scheduleRetry();
          break;
        }
      }
    } finally {
      this.syncing = false;
    }
  }

  private scheduleRetry() {
    if (!this.alive || this.retryTimer !== undefined) return;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = undefined;
      void this.flushGameState();
    }, 1000);
  }

  private async syncArtwork(appid: number, status: Status, generation: number) {
    await Promise.all([
      this.syncArtworkPurpose(appid, status, generation, status.artwork_source, "artwork"),
      this.syncArtworkPurpose(appid, status, generation, status.launch_artwork_source, "launch"),
    ]);
  }

  private async syncArtworkPurpose(
    appid: number,
    status: Status,
    generation: number,
    source: Status["artwork_source"],
    purpose: "artwork" | "launch",
  ) {
    try {
      const artwork = await getArtwork(appid, source, purpose);
      if (!this.alive || generation !== this.artworkGeneration || this.desired.appid !== appid) return;
      if (!artwork.found || !artwork.data_uri || !artwork.fingerprint || artwork.cached) return;
      const result = await sampleArtwork(artwork.data_uri, status.artwork_mode, status.artwork_manual_y);
      if (!this.alive || generation !== this.artworkGeneration || this.desired.appid !== appid) return;
      await submitArtwork(
        appid,
        artwork.fingerprint,
        result.colors,
        result.y,
        result.dominantPalettes,
        artwork.filename ?? "",
        artwork.source ?? source,
        purpose,
      );
    } catch (error) {
      console.warn(`[GabeCubeAura] background ${purpose} artwork sampling failed`, error);
    }
  }

  private handleParentalMinutes(appid: number, minutes: number) {
    const callbackDelay = this.parentalWaitStartedAt
      ? Math.max(0, Date.now() - this.parentalWaitStartedAt)
      : 0;
    this.parentalWaitStartedAt = 0;
    void reportRuntimeDiagnostic(
      "parental_received", appid, "Steam callback", callbackDelay,
    ).catch((error) => console.warn("[GabeCubeAura] runtime diagnostic failed", error));
    void reportParentalMinutes(minutes).catch((error) => {
      console.warn("[GabeCubeAura] parental playtime signal failed", error);
    });
  }

  private registerSteamEvents() {
    this.parental.selectApp(0);
    this.registerLightEvents();
    this.registerControllerSignals();
    try {
      const registerLifetime = SteamClient?.GameSessions?.RegisterForAppLifetimeNotifications;
      if (typeof registerLifetime === "function") {
        this.session.setLifetimeAvailable(true);
        this.gameRegistration = registerLifetime.call(SteamClient.GameSessions, (event: any) => {
          const appid = normalizeAppId(event?.unAppID);
          this.applySessionDecision(this.session.observeLifetime(
            appid,
            Boolean(event?.bRunning),
            titleFor(appid) || runningApp().title,
          ));
        });
      }
    } catch (error) {
      this.session.setLifetimeAvailable(false);
      console.warn("[GabeCubeAura] Steam game hook unavailable", error);
    }
    try {
      this.resumeRegistration = SteamClient?.System?.RegisterForOnResumeFromSuspend?.(() => {
        void this.controllerMonitor?.refresh();
        this.parental.selectApp(0);
        this.parentalWaitStartedAt = 0;
        const stale = runningApp();
        this.applySessionDecision(this.session.suspend(stale.appid));
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam resume hook unavailable", error);
    }
    try {
      this.downloadRegistration = SteamClient?.Downloads?.RegisterForDownloadOverview?.((overview: any) => {
        this.setDownloadActivity(downloadOverviewActive(overview), "overview");
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam download hook unavailable", error);
    }
    try {
      this.downloadItemsRegistration = SteamClient?.Downloads?.RegisterForDownloadItems?.((
        _listChanged: boolean,
        downloadItems: unknown[],
      ) => {
        if (!Array.isArray(downloadItems)) return;
        this.setDownloadActivity(downloadItemsActive(downloadItems), "items");
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam download item hook unavailable", error);
    }
  }

  private setDownloadActivity(active: boolean, source: "overview" | "items") {
    if (source === "items") {
      this.downloadItemsSeen = true;
      this.downloadItemsActive = active;
    } else {
      this.downloadOverviewActive = active;
    }
    const decision = resolveDownloadActivity(
      this.downloadOverviewActive,
      this.downloadItemsActive,
      this.downloadItemsSeen,
    );
    this.downloadActive = decision.active;
    this.downloadActivitySource = decision.source;
    this.renewSteamActivity();
  }

  private renewSteamActivity() {
    this.steamActivityDirty = true;
    if (this.steamActivitySyncing) return;
    this.steamActivitySyncing = true;
    void this.syncSteamActivity().finally(() => {
      this.steamActivitySyncing = false;
      if (this.steamActivityDirty && this.alive) this.renewSteamActivity();
    });
  }

  private async syncSteamActivity() {
    while (this.steamActivityDirty && this.alive) {
      this.steamActivityDirty = false;
      const active = this.downloadActive;
      try {
        const recovered = await this.steamLedRecovery;
        if (this.steamLedOverrideState === "" && recovered !== "inactive") {
          this.steamLedOverrideState = recovered;
        }
        const policy = await setSteamActivity(
          active,
          active ? `Steam download activity (${this.downloadActivitySource})` : "",
        );
        if (!this.alive) {
          this.downloadLedOverride.stop();
          return;
        }
        const suppressDownload = active && policy.suppress_download_animation;
        const restoreDownload = active && policy.restore_download_animation;
        let state: SteamDownloadOverrideState;
        if (restoreDownload && !await this.waitForValveDownloadHandoff()) {
          state = "error";
        } else {
          state = await this.downloadLedOverride.update(
            suppressDownload,
            restoreDownload,
          );
        }
        if (state !== this.steamLedOverrideState) {
          this.steamLedOverrideState = state;
          await reportRuntimeDiagnostic(
            "steam_led_override", 0, state, 0,
          ).catch(() => undefined);
        }
      } catch (error) {
        this.downloadLedOverride.stop();
        if (this.steamLedOverrideState !== "error") {
          this.steamLedOverrideState = "error";
          await reportRuntimeDiagnostic(
            "steam_led_override", 0, "error", 0,
          ).catch(() => undefined);
        }
        console.warn("[GabeCubeAura] Steam activity sync failed", error);
      }
    }
  }

  private async waitForValveDownloadHandoff(): Promise<boolean> {
    const deadline = Date.now() + 1200;
    while (this.alive && this.downloadActive && Date.now() < deadline) {
      try {
        const status = await getStatus();
        if (status.owner === "Valve" && status.provider === "valve") return true;
      } catch {
        // The backend may be restarting at the same time as Decky's frontend.
      }
      await wait(50);
    }
    return false;
  }

  private async pollScreensaver() {
    if (!this.alive || this.screensaverPolling) return;
    this.screensaverPolling = true;
    try {
      this.screensaverService ??= findModuleExport(isSteamScreensaverService);
      if (!this.screensaverService) {
        await setScreenSyncContext(
          "steam-screensaver", false, "unavailable", "Steam screensaver service was not found",
        );
        return;
      }
      this.ensureScreensaverStateRegistration();
      const response = await Promise.race([
        Promise.resolve(this.screensaverService.GetActiveState({})),
        new Promise<never>((_resolve, reject) => window.setTimeout(
          () => reject(new Error("Steam screensaver state timed out")),
          1200,
        )),
      ]);
      const active = screensaverActiveFromResponse(response);
      if (active === null) throw new Error("Steam screensaver state was not recognised");
      this.screensaverFailures = 0;
      await setScreenSyncContext("steam-screensaver", active, "available", "");
    } catch (error) {
      this.screensaverFailures += 1;
      if (this.screensaverFailures >= 2) {
        this.unregisterScreensaverState();
        this.screensaverService = undefined;
      }
      await setScreenSyncContext(
        "steam-screensaver",
        false,
        "error",
        String(error instanceof Error ? error.message : error).slice(0, 180),
      ).catch(() => undefined);
    } finally {
      this.screensaverPolling = false;
    }
  }

  private ensureScreensaverStateRegistration() {
    if (!this.screensaverService || this.screensaverRegistrationAttempted) return;
    this.screensaverRegistrationAttempted = true;
    this.screensaverRegistration = registerForScreensaverState(
      this.screensaverService,
      (response) => {
        if (!this.alive) return;
        const active = screensaverActiveFromResponse(response);
        if (active === null) return;
        this.screensaverFailures = 0;
        void setScreenSyncContext(
          "steam-screensaver", active, "available", "",
        ).catch(() => undefined);
      },
    );
  }

  private unregisterScreensaverState() {
    try {
      if (this.screensaverRegistration?.unregister) {
        this.screensaverRegistration.unregister();
      } else {
        this.screensaverRegistration?.Unregister?.();
      }
    } catch {
      // The bounded polling path remains safe if Steam invalidated the handle.
    }
    this.screensaverRegistration = undefined;
    this.screensaverRegistrationAttempted = false;
  }

  private emitLightEvent(kind: LightEvent) {
    if (!this.alive) return;
    void triggerEvent(kind, false, "").catch((error) => {
      console.warn(`[GabeCubeAura] ${kind} event was not delivered`, error);
    });
  }

  private registerLightEvents() {
    try {
      this.screenshotRegistration = SteamClient?.GameSessions?.RegisterForScreenshotNotification?.((notice: any) => {
        if (screenshotWasCaptured(notice)) this.emitLightEvent("screenshot");
      });
    } catch (error) {
      console.warn("[GabeCubeAura] screenshot hook unavailable", error);
    }
    try {
      // The callback's index identifies a notification-list position, not a
      // durable event ID. Caching it could suppress later, unrelated notices.
      this.notificationsRegistration = SteamClient?.Notifications?.RegisterForNotifications?.(
        (_index: number, type: number) => {
          if (!this.alive) return;
          const numericType = Number(type);
          const kind = classifySteamNotification(numericType);
          if (!kind) return;
          if (numericType === 27) {
            const now = Date.now();
            const duplicatesServerEvent = now - this.lastServerCommentAt < 2500;
            this.lastNativeCommentAt = now;
            if (duplicatesServerEvent) return;
          }
          this.emitLightEvent(kind);
        },
      );
    } catch (error) {
      console.warn("[GabeCubeAura] Steam notification hook unavailable", error);
    }
    this.communityNotificationObserver.reset();
    this.lastNativeCommentAt = 0;
    this.lastServerCommentAt = 0;
    this.scanCommunityNotifications();
    this.communityNotificationsTimer = window.setInterval(
      () => this.scanCommunityNotifications(),
      1000,
    );
  }

  private scanCommunityNotifications() {
    if (!this.alive) return;
    try {
      if (!this.communityNotificationStore) {
        this.communityNotificationStore = findModuleExport(isSteamServerNotificationStore);
        if (this.communityNotificationStore) {
          console.log("[GabeCubeAura] Steam Community notification centre connected");
        }
      }
      const events = this.communityNotificationObserver.scan(this.communityNotificationStore);
      events.forEach((event) => {
        if (event.type === 3) {
          const now = Date.now();
          const duplicatesNativeEvent = now - this.lastNativeCommentAt < 2500;
          this.lastServerCommentAt = now;
          if (duplicatesNativeEvent) return;
        }
        this.emitLightEvent("notification");
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam Community notification hook unavailable", error);
    }
  }

  private registerControllerSignals() {
    let controllerStore: SteamControllerStore | undefined;
    this.controllerMonitor = new ControllerMonitor({
      discover: () => findModuleExport(isSteamInputService),
      readStore: () => {
        controllerStore ??= findModuleExport(isSteamControllerStore);
        return controllerStore?.GetControllers();
      },
      publish: updateControllers,
      diagnose: reportControllerTelemetry,
    });
    this.controllerMonitor.start();
  }
}

export function startGabeCubeAuraRuntime() {
  const runtime = new GabeCubeAuraRuntime();
  runtime.start();
  return runtime;
}
