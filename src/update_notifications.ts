import { Navigation } from "@decky/ui";
import { toaster } from "@decky/api";

import { acknowledgeUpdateNotification, getStatus, getUpdateStatus } from "./api";
import { shouldNotifyUpdate } from "./update_logic";
import { setUILanguage, translate } from "./i18n";

class UpdateNotificationMonitor {
  private alive = false;
  private timer: number | undefined;
  private checking = false;

  start() {
    if (this.alive) return;
    this.alive = true;
    void this.poll();
    this.timer = window.setInterval(() => void this.poll(), 30_000);
  }

  stop() {
    this.alive = false;
    if (this.timer !== undefined) window.clearInterval(this.timer);
    this.timer = undefined;
  }

  private async poll() {
    if (!this.alive || this.checking) return;
    this.checking = true;
    try {
      const [update, status] = await Promise.all([getUpdateStatus(), getStatus()]);
      setUILanguage(status.ui_language);
      if (!this.alive || !shouldNotifyUpdate(update, status.game.appid)) return;
      toaster.toast({
        title: translate(`GabeCubeAura ${update.available_version} is available`),
        body: translate("Open Updates to see what changed and install it."),
        duration: 7000,
        showToast: true,
        playSound: false,
        onClick: () => {
          Navigation.CloseSideMenus();
          Navigation.Navigate("/gabecubeaura/settings/updates");
        },
      });
      await acknowledgeUpdateNotification(update.available_version);
    } catch (error) {
      console.warn("[GabeCubeAura] update notification check failed", error);
    } finally {
      this.checking = false;
    }
  }
}

export function startUpdateNotifications() {
  const monitor = new UpdateNotificationMonitor();
  monitor.start();
  return monitor;
}
