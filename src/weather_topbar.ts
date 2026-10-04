/* SteamOS top-bar weather indicator.

Decky does not expose a stable top-bar slot. This feature deliberately mounts
only when a plausible clock/icon row is found in Steam's main UI document. It
never appends an orphan indicator to the plugin document or overlays the game.
*/

import { Router } from "@decky/ui";
import { getStatus } from "./api";
import { weatherIconSvg } from "./weather_icon_sets";
import { weatherTopBarReading } from "./weather_topbar_model";

const ROOT_ID = "gabecubeaura-weather-topbar";
const REFRESH_MS = 5_000;
const CLOCK = /^\d{1,2}:\d{2}(?:\s*[AP]M)?$/i;

function visibleTopRight(element: HTMLElement, viewport: number): boolean {
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0 && box.top >= -8 && box.top < 115
    && box.right > viewport * 0.52;
}

function findAnchor(doc: Document): { row: HTMLElement; before: Element | null } | null {
  const view = doc.defaultView;
  if (!view || !doc.body) return null;
  const viewport = view.innerWidth;
  // Prefer the clock. Insert before its direct child in the shared icon row.
  for (const leaf of Array.from(doc.querySelectorAll<HTMLElement>("span,div"))) {
    if (leaf.children.length || !CLOCK.test((leaf.textContent ?? "").trim())
        || !visibleTopRight(leaf, viewport)) continue;
    let child: HTMLElement = leaf;
    for (let depth = 0; depth < 5 && child.parentElement; depth++) {
      const row: HTMLElement = child.parentElement;
      const box = row.getBoundingClientRect();
      const display = view.getComputedStyle(row).display;
      if (row.children.length >= 2 && box.width >= 120 && box.height < 80 && visibleTopRight(row, viewport)
          && (display === "flex" || display === "inline-flex")) {
        return { row, before: child };
      }
      child = row;
    }
  }
  // Steam can change the clock markup. A compact top-right icon row is a
  // fallback, but never append to the document body as a floating overlay.
  const buttons = Array.from(doc.querySelectorAll<HTMLElement>("button,[role='button']"))
    .filter((button) => visibleTopRight(button, viewport));
  for (const button of buttons) {
    let child: HTMLElement = button;
    for (let depth = 0; depth < 4 && child.parentElement; depth++) {
      const row: HTMLElement = child.parentElement;
      const box = row.getBoundingClientRect();
      if (row.children.length >= 3 && box.width >= 120 && box.height < 80
          && visibleTopRight(row, viewport)
          && buttons.filter((candidate) => row.contains(candidate)).length >= 3) {
        return { row, before: child };
      }
      child = row;
    }
  }
  return null;
}

function mainSteamAnchor(): { doc: Document; row: HTMLElement; before: Element | null } | null {
  let routerWindow: Window | undefined;
  let steamWindow: Window | undefined;
  try {
    routerWindow = (Router as unknown as { WindowStore?: { GamepadUIMainWindowInstance?: { BrowserWindow?: Window } } })
      ?.WindowStore?.GamepadUIMainWindowInstance?.BrowserWindow;
  } catch { /* Steam's store is not available yet. */ }
  try {
    steamWindow = (window as unknown as { SteamUIStore?: { GetFocusedWindowInstance?: () => { BrowserWindow?: Window } } })
      .SteamUIStore?.GetFocusedWindowInstance?.()?.BrowserWindow;
  } catch { /* Steam's store is not available yet. */ }
  for (const candidate of [routerWindow, steamWindow, window.top]) {
    try {
      if (!candidate?.document?.body) continue;
      const anchor = findAnchor(candidate.document);
      if (anchor) return { doc: candidate.document, ...anchor };
    } catch { /* Other CEF process: do not inject there. */ }
  }
  return null;
}

class WeatherTopBar {
  private interval: number | null = null;
  private remountTimer: number | null = null;
  private observer: MutationObserver | null = null;
  private document: Document | null = null;
  private root: HTMLSpanElement | null = null;
  private icon: HTMLSpanElement | null = null;
  private value: HTMLSpanElement | null = null;
  private reading: ReturnType<typeof weatherTopBarReading> = null;
  private stopped = false;
  private fetching = false;

  start() {
    void this.refresh();
    this.interval = window.setInterval(() => void this.refresh(), REFRESH_MS);
  }

  stop() {
    this.stopped = true;
    if (this.interval != null) window.clearInterval(this.interval);
    if (this.remountTimer != null) window.clearTimeout(this.remountTimer);
    this.observer?.disconnect();
    this.root?.remove();
    this.root = null;
    this.document = null;
  }

  private async refresh() {
    if (this.stopped || this.fetching) return;
    this.fetching = true;
    try {
      this.reading = weatherTopBarReading(await getStatus());
      if (!this.stopped) this.mount();
    } catch {
      // Keep the last reading through a transient Decky RPC error. The next
      // successful status checks age and removes stale readings.
    } finally {
      this.fetching = false;
    }
  }

  private watch(doc: Document) {
    this.observer?.disconnect();
    this.observer = null;
    const observerType = doc.defaultView?.MutationObserver;
    if (!observerType || !doc.body) return;
    this.observer = new observerType(() => {
      if (this.root?.isConnected) return;
      if (this.remountTimer != null || this.stopped) return;
      this.remountTimer = window.setTimeout(() => {
        this.remountTimer = null;
        this.mount();
      }, 250);
    });
    this.observer.observe(doc.body, { childList: true, subtree: true });
  }

  private mount() {
    if (this.stopped || !this.reading) {
      this.root?.remove();
      this.observer?.disconnect();
      this.observer = null;
      this.root = null;
      this.icon = null;
      this.value = null;
      this.document = null;
      return;
    }
    const anchor = mainSteamAnchor();
    if (!anchor) { this.root?.remove(); return; }
    const { doc } = anchor;
    if (this.document !== doc) {
      this.root?.remove();
      this.root = null;
      this.document = doc;
      this.watch(doc);
    }
    if (!this.root) {
      doc.getElementById(ROOT_ID)?.remove();
      this.root = doc.createElement("span");
      this.root.id = ROOT_ID;
      this.root.setAttribute("role", "status");
      this.root.style.cssText = "display:inline-flex;align-items:center;gap:4px;margin:0 7px;color:inherit;white-space:nowrap;font-size:14px;line-height:1;pointer-events:none;flex-shrink:0";
      this.icon = doc.createElement("span");
      this.icon.style.cssText = "display:inline-flex;width:17px;height:17px;align-items:center;justify-content:center";
      this.value = doc.createElement("span");
      this.root.append(this.icon, this.value);
    }
    if (this.root.parentElement !== anchor.row || this.root.nextElementSibling !== anchor.before) {
      anchor.row.insertBefore(this.root, anchor.before);
    }
    const svg = weatherIconSvg(this.reading.icon_style, this.reading.condition);
    if (this.icon!.innerHTML !== svg) this.icon!.innerHTML = svg;
    if (this.value!.textContent !== this.reading.text) this.value!.textContent = this.reading.text;
    if (this.root.getAttribute("aria-label") !== this.reading.title) {
      this.root.setAttribute("aria-label", this.reading.title);
      this.root.title = this.reading.title;
    }
  }
}

export function startWeatherTopBar() {
  const indicator = new WeatherTopBar();
  indicator.start();
  return indicator;
}
