import { Router, findModuleExport } from "@decky/ui";
import {fetchNoCors} from '@decky/api';
import {PlayerCityTransport} from './player_city_transport';

import {
  gameChanged,
  reportDashboardStats,
  claimPlayerCityPoll,
  completePlayerCityPoll,
  getArtwork,
  getStatus,
  reportParentalMinutes,
  reportRuntimeDiagnostic,
  setSteamActivity,
  triggerEvent,
  updateControllers,
  resetControllers,
  reportControllerTelemetry,
  resumeFaceplate,
  setScreenSyncContext,
} from "./api";
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
import {steamDashboardStats, isSteamAppDetailsStore,type SteamAppDetailsStore} from "./steam_dashboard_stats";
import { ScreensaverContextQueue } from "./screensaver_context_queue";

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
  private playerCity=new PlayerCityTransport({claim:claimPlayerCityPoll,complete:completePlayerCityPoll,fetch:fetchNoCors});
  private dashboardStatsAt = 0;
  private dashboardStatsKey = '';
  private dashboardDetails: SteamAppDetailsStore | undefined;
  private dashboardDetailsApp = 0;
  private dashboardDetailsEpoch = 0;
  private dashboardDetailsRegistration: Registration;
  private dashboardStatsAgain = false;
  private dashboardStatsRetries = new Set<number>();
  private dashboardStatsBusy = false;
  private dashboardDetailsProbeAt = 0;
  private generation = 0;
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
  private screensaverObservation = 0;
  private screensaverContext = new ScreensaverContextQueue(value =>
    setScreenSyncContext("steam-screensaver",value.active,value.detection,value.detail));

  start() {
    if (this.alive) return;
    this.alive = true;
    this.playerCity.start();
    this.generation += 1;
    this.desired = { appid: 0, title: "", source: "startup", launchSequence: 0 };
    this.baselineEstablished = false;
    this.confirmedKey = "";
    this.session = new GameSessionLatch();
    this.screensaverObservation += 1;
    this.steamLedRecovery = this.downloadLedOverride.recoverAfterRestart();
    this.applySessionDecision(this.session.seed(runningApp()));
    // Establish the observed AppID before lifetime notifications are attached.
    // Some Steam builds replay the currently running session immediately.
    this.baselineEstablished = true;
    this.registerSteamEvents();
    this.renewSteamActivity();
    const lifetime = this.generation;
    this.pollTimer = window.setInterval(() => {
      if (!this.alive || lifetime !== this.generation) return;
      this.observeRunningApp();
      void this.syncDashboardStats();
      void this.playerCity.poll();
      this.renewSteamActivity();
      void this.pollScreensaver();
    }, 2000);
    void this.screensaverContext.submit({active:false,detection:"waiting",detail:"startup"});
    void this.pollScreensaver();
    console.log("[GabeCubeAura] background runtime started");
  }

  stop() {
    this.alive = false;
    this.playerCity.stop();
    this.clearDashboardSubscription();
    this.generation += 1;
    this.artworkGeneration += 1;
    this.syncing = false;
    this.steamActivitySyncing = false;
    this.screensaverPolling = false;
    this.screensaverObservation += 1;
    if (this.pollTimer !== undefined) window.clearInterval(this.pollTimer);
    if (this.communityNotificationsTimer !== undefined) {
      window.clearInterval(this.communityNotificationsTimer);
      this.communityNotificationsTimer = undefined;
    }
    if (this.retryTimer !== undefined) window.clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    for (const registration of [this.gameRegistration, this.downloadRegistration,
      this.downloadItemsRegistration, this.resumeRegistration,
      this.notificationsRegistration, this.screenshotRegistration]) {
      try { registration?.unregister?.(); }
      catch (error) { console.warn('[GabeCubeAura] stale Steam registration during cleanup', error); }
    }
    this.parental.stop();
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
    const stoppedGeneration = this.generation;
    void this.controllerMonitor?.stop().then(() => {
      if (!this.alive && stoppedGeneration === this.generation) return resetControllers();
      return undefined;
    }).catch(console.warn);
    void setSteamActivity(false, "").catch(() => undefined);
    void this.screensaverContext.submit({active:false,detection:"waiting",detail:"stopped"});
    console.log("[GabeCubeAura] background runtime stopped");
  }

  private observeRunningApp() {
    if (!this.alive) return;
    this.applySessionDecision(this.session.observePoll(runningApp()));
    this.parental.ensure();
    void reportRuntimeDiagnostic(
      "heartbeat", this.desired.appid, "background runtime", 0,
    ).catch(() => undefined);
  }

  private applySessionDecision(decision: GameSessionDecision) {
    if (!this.alive) return;
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

  private clearDashboardSubscription() {
    this.dashboardDetailsApp=0;this.dashboardDetailsEpoch++;
    try {this.dashboardDetailsRegistration?.unregister?.();} catch { /* Steam reload. */ }
    this.dashboardDetailsRegistration=undefined;
    for(const timer of this.dashboardStatsRetries)window.clearTimeout(timer);
    this.dashboardStatsRetries.clear();this.dashboardStatsAgain=false;
    this.dashboardStatsAt=0;this.dashboardStatsKey='';
  }

  private subscribeDashboardStats(appid:number) {
    if(!this.dashboardDetails||this.dashboardDetailsApp===appid)return;
    this.dashboardDetailsApp=appid;const lifetime=this.generation,epoch=this.dashboardDetailsEpoch;
    try {
      this.dashboardDetailsRegistration=this.dashboardDetails.RegisterForAppData(appid,()=>{
        if(!this.alive||lifetime!==this.generation||this.desired.appid!==appid||this.dashboardDetailsApp!==appid||epoch!==this.dashboardDetailsEpoch)return;
        // Steam invokes this once immediately, then whenever the loaded details
        // change. Defer the first callback to avoid recursive registration.
        void Promise.resolve().then(()=>{
          if(this.alive&&lifetime===this.generation&&this.desired.appid===appid&&this.dashboardDetailsApp===appid&&epoch===this.dashboardDetailsEpoch)void this.syncDashboardStats(true);
        });
      });
    }catch{this.dashboardDetailsApp=0;}
  }

  private refreshAchievementStats() {
    const appid=this.desired.appid,lifetime=this.generation;
    if(appid<=0)return;
    void this.syncDashboardStats(true);
    // Notification delivery may precede Steam's details update. The native
    // subscription is primary; a short bounded retry also covers missing hooks.
    for(const timer of this.dashboardStatsRetries)window.clearTimeout(timer);
    this.dashboardStatsRetries.clear();
    for(const delay of [250,1000,3000]){
      const timer=window.setTimeout(()=>{this.dashboardStatsRetries.delete(timer);
        if(this.alive&&lifetime===this.generation&&this.desired.appid===appid)void this.syncDashboardStats(true);
      },delay);this.dashboardStatsRetries.add(timer);
    }
  }

  private async syncDashboardStats(force = false) {
    const appid = this.desired.appid;
    const generation = this.generation,epoch=this.dashboardDetailsEpoch;
    if (!this.alive || appid <= 0) return;
    if(this.dashboardStatsBusy){if(force)this.dashboardStatsAgain=true;return;}
    const now = Date.now();
    if (!force && now - this.dashboardStatsAt < 5000) return;
    try {
      if (!this.dashboardDetails && (force || now - this.dashboardDetailsProbeAt >= 30000)) {
        this.dashboardDetailsProbeAt = now;
        try { this.dashboardDetails = findModuleExport(isSteamAppDetailsStore); } catch { /* Retry later. */ }
      }
      this.subscribeDashboardStats(appid);
      let overview: unknown, details: unknown;
      try { overview = typeof appStore !== "undefined" ? appStore?.GetAppOverviewByAppID?.(appid) : undefined; } catch { /* Other fields can still be ready. */ }
      try { details = this.dashboardDetails?.GetAppDetails(appid); } catch { /* Keep the loaded total. */ }
      const stats = steamDashboardStats(overview, details);
      const key = JSON.stringify([appid, stats]);
      if (!force && key === this.dashboardStatsKey && now - this.dashboardStatsAt < 20000) return;
      this.dashboardStatsBusy = true;
      const accepted = await reportDashboardStats(appid, {...stats});
      if (accepted && this.alive && generation === this.generation && epoch===this.dashboardDetailsEpoch && appid === this.desired.appid) {
        this.dashboardStatsKey = key; this.dashboardStatsAt = now;
      }
    } catch { /* Local file caches remain available when SteamUI has no details. */ }
    finally { this.dashboardStatsBusy = false;
      if(this.dashboardStatsAgain){this.dashboardStatsAgain=false;void this.syncDashboardStats(true);}
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
      this.clearDashboardSubscription();
      this.artworkGeneration += 1;
    }
    void this.flushGameState();
  }

  private async flushGameState() {
    if (this.syncing || !this.alive) return;
    this.syncing = true;
    const lifetime = this.generation;
    try {
      while (this.alive && lifetime === this.generation) {
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
          if (!this.alive || lifetime !== this.generation) return;
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
          void this.syncDashboardStats(true);
          void this.playerCity.poll();
          if (current.appid > 0) {
            const generation = this.artworkGeneration;
            void this.syncArtwork(current.appid, status, generation);
          }
        } catch (error) {
          if (!this.alive || lifetime !== this.generation) return;
          console.warn("[GabeCubeAura] background game sync failed; retrying", error);
          this.scheduleRetry();
          break;
        }
      }
    } finally {
      if (lifetime === this.generation) this.syncing = false;
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
      this.syncArtworkPurpose(appid, generation, status.artwork_source, "artwork"),
      this.syncArtworkPurpose(appid, generation, status.launch_artwork_source, "launch"),
    ]);
  }

  private async syncArtworkPurpose(
    appid: number,
    generation: number,
    source: Status["artwork_source"],
    purpose: "artwork" | "launch",
  ) {
    try {
      if (!this.alive || generation !== this.artworkGeneration || this.desired.appid !== appid) return;
      await getArtwork(appid, source, purpose, false);
      if (!this.alive || generation !== this.artworkGeneration || this.desired.appid !== appid) return;
    } catch (error) {
      if (!this.alive || generation !== this.artworkGeneration) return;
      console.warn(`[GabeCubeAura] background ${purpose} cache activation failed`, error);
    }
  }

  private handleParentalMinutes(appid: number, minutes: number) {
    if (!this.alive || this.desired.appid !== appid) return;
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
    const lifetime = this.generation;
    const current = () => this.alive && lifetime === this.generation;
    this.parental.selectApp(0);
    this.registerLightEvents();
    this.registerControllerSignals();
    try {
      const registerLifetime = SteamClient?.GameSessions?.RegisterForAppLifetimeNotifications;
      if (typeof registerLifetime === "function") {
        this.session.setLifetimeAvailable(true);
        this.gameRegistration = registerLifetime.call(SteamClient.GameSessions, (event: any) => {
          if (!current()) return;
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
        if (!current()) return;
        this.screensaverObservation += 1;
        this.unregisterScreensaverState();
        this.screensaverService=undefined;
        void resumeFaceplate().catch((error) => {
          console.warn("[GabeCubeAura] faceplate resume recovery failed", error);
        });
        void this.controllerMonitor?.refresh();
        this.parental.selectApp(0);
        this.parentalWaitStartedAt = 0;
        const stale = runningApp();
        this.applySessionDecision(this.session.suspend(stale.appid));
        void this.pollScreensaver();
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam resume hook unavailable", error);
    }
    try {
      this.downloadRegistration = SteamClient?.Downloads?.RegisterForDownloadOverview?.((overview: any) => {
        if (!current()) return;
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
        if (!current() || !Array.isArray(downloadItems)) return;
        this.setDownloadActivity(downloadItemsActive(downloadItems), "items");
      });
    } catch (error) {
      console.warn("[GabeCubeAura] Steam download item hook unavailable", error);
    }
  }

  private setDownloadActivity(active: boolean, source: "overview" | "items") {
    if (!this.alive) return;
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
    if (!this.alive) return;
    const lifetime = this.generation;
    this.steamActivityDirty = true;
    if (this.steamActivitySyncing) return;
    this.steamActivitySyncing = true;
    void this.syncSteamActivity(lifetime).finally(() => {
      if (lifetime !== this.generation) return;
      this.steamActivitySyncing = false;
      if (this.steamActivityDirty && this.alive) this.renewSteamActivity();
    });
  }

  private async syncSteamActivity(lifetime = this.generation) {
    while (this.steamActivityDirty && this.alive && lifetime === this.generation) {
      this.steamActivityDirty = false;
      const active = this.downloadActive;
      try {
        const recovered = await this.steamLedRecovery;
        if (!this.alive || lifetime !== this.generation) return;
        if (this.steamLedOverrideState === "" && recovered !== "inactive") {
          this.steamLedOverrideState = recovered;
        }
        const policy = await setSteamActivity(
          active,
          active ? `Steam download activity (${this.downloadActivitySource})` : "",
        );
        if (!this.alive || lifetime !== this.generation) return;
        const suppressDownload = active && policy.suppress_download_animation;
        const restoreDownload = active && policy.restore_download_animation;
        let state: SteamDownloadOverrideState;
        const handoff = !restoreDownload || await this.waitForValveDownloadHandoff(lifetime);
        if (!this.alive || lifetime !== this.generation) return;
        if (!handoff) {
          state = "error";
        } else {
          state = await this.downloadLedOverride.update(
            suppressDownload,
            restoreDownload,
          );
        }
        if (!this.alive || lifetime !== this.generation) return;
        if (state !== this.steamLedOverrideState) {
          this.steamLedOverrideState = state;
          await reportRuntimeDiagnostic(
            "steam_led_override", 0, state, 0,
          ).catch(() => undefined);
        }
      } catch (error) {
        if (!this.alive || lifetime !== this.generation) return;
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

  private async waitForValveDownloadHandoff(lifetime = this.generation): Promise<boolean> {
    const deadline = Date.now() + 1200;
    while (this.alive && lifetime === this.generation && this.downloadActive && Date.now() < deadline) {
      try {
        const status = await getStatus();
        if (!this.alive || lifetime !== this.generation) return false;
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
    const observation = this.screensaverObservation;
    const lifetime = this.generation;
    let stateTimeout:number|undefined;
    try {
      this.screensaverService ??= findModuleExport(isSteamScreensaverService);
      if (!this.screensaverService) {
        await this.screensaverContext.submit({active:false,detection:"unavailable",detail:"Steam screensaver service was not found"},
          ()=>this.alive&&observation===this.screensaverObservation);
        return;
      }
      this.ensureScreensaverStateRegistration();
      const response = await Promise.race([
        Promise.resolve(this.screensaverService.GetActiveState({})),
        new Promise<never>((_resolve, reject) => {stateTimeout=window.setTimeout(
          () => reject(new Error("Steam screensaver state timed out")),
          1200,
        );}),
      ]);
      const active = screensaverActiveFromResponse(response);
      if (active === null) throw new Error("Steam screensaver state was not recognised");
      // A native notification or teardown is newer evidence than an in-flight
      // GetActiveState reply. Never revive a closed activation with that reply.
      if (!this.alive || observation !== this.screensaverObservation) return;
      this.screensaverFailures = 0;
      await this.screensaverContext.submit({active,detection:"available",detail:"poll"},
        ()=>this.alive&&observation===this.screensaverObservation);
    } catch (error) {
      if (!this.alive || observation !== this.screensaverObservation) return;
      this.screensaverFailures += 1;
      if (this.screensaverFailures >= 2) {
        this.unregisterScreensaverState();
        this.screensaverService = undefined;
      }
      await this.screensaverContext.submit({active:false,detection:"error",
        detail:String(error instanceof Error ? error.message : error).slice(0,180)},
        ()=>this.alive&&observation===this.screensaverObservation);
    } finally {
      if(stateTimeout!==undefined)window.clearTimeout(stateTimeout);
      if (lifetime === this.generation) this.screensaverPolling = false;
    }
  }

  private ensureScreensaverStateRegistration() {
    if (!this.screensaverService || this.screensaverRegistrationAttempted) return;
    const service=this.screensaverService;
    const lifetime=this.generation;
    this.screensaverRegistrationAttempted = true;
    this.screensaverRegistration = registerForScreensaverState(
      this.screensaverService,
      (response) => {
        if (!this.alive || lifetime!==this.generation || service!==this.screensaverService) return;
        const active = screensaverActiveFromResponse(response);
        if (active === null) return;
        this.screensaverObservation += 1;
        this.screensaverFailures = 0;
        const observation=this.screensaverObservation;
        void this.screensaverContext.submit({active,detection:"available",detail:"notification"},
          ()=>this.alive&&(!active||observation===this.screensaverObservation));
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
    if(kind==="achievement")this.refreshAchievementStats();
    void triggerEvent(kind, false, "").catch((error) => {
      console.warn(`[GabeCubeAura] ${kind} event was not delivered`, error);
    });
  }

  private registerLightEvents() {
    const lifetime = this.generation;
    try {
      this.screenshotRegistration = SteamClient?.GameSessions?.RegisterForScreenshotNotification?.((notice: any) => {
        if (!this.alive || lifetime !== this.generation) return;
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
          if (!this.alive || lifetime !== this.generation) return;
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
      () => { if (this.alive && lifetime === this.generation) this.scanCommunityNotifications(); },
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
