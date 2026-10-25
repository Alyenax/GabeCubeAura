import { translate } from "./i18n";

export const PERFORMANCE_CONSENT = "faceplate-performance-unlimited-v1";
export const PERFORMANCE_WARNING_TITLE = "CPU/GPU faceplate: memory wear risk";
export const PERFORMANCE_ACCEPT = "I understand the risks and enable";
export const PERFORMANCE_WARNING_RISK = "Each changed CPU/GPU image may be written to the faceplate's persistent memory. Frequent transfers may accelerate memory wear and shorten the device's service life. The actual endurance and internal write management are unknown. Neither 5 seconds nor 1 second is a proven safe interval.";
export const PERFORMANCE_WARNING_EXEMPTION = "After confirmation, CPU/GPU transfers are exempt from the 120-per-hour limit and the global GIF rate budget, even when memory protection is enabled. Other displays remain protected. USB brightness and thermal safeguards remain active.";
export const PERFORMANCE_WARNING_RESPONSIBILITY = "You enable this experimental feature voluntarily, at your own risk, with no guarantee of hardware longevity. To the extent permitted by applicable law, the authors and contributors disclaim liability for hardware wear or damage resulting from its use.";

export function performanceWarningParagraphs(seconds = 5): string[] {
  const interval = Math.max(1, Math.min(60, Math.round(seconds)));
  return [
    translate("Default refresh: every 5 seconds, adjustable down to 1 second."),
    translate("Selected interval: {0} seconds. Up to {1} new GIF transfers per hour if values keep changing; actual USB transfer time may reduce this rate.")
      .replace("{0}", String(interval)).replace("{1}", String(Math.floor(3600 / interval))),
    translate(PERFORMANCE_WARNING_RISK), translate(PERFORMANCE_WARNING_EXEMPTION),
    translate(PERFORMANCE_WARNING_RESPONSIBILITY),
  ];
}

export function performanceWarningBody(seconds = 5): string {
  return performanceWarningParagraphs(seconds).join("\n\n");
}

export function requiresPerformanceConsent(home: string, game: string, previousHome: string,
                                           previousGame: string, consent?: string): boolean {
  return (home === "performance" && (previousHome !== home || consent !== PERFORMANCE_CONSENT))
    || (game === "performance" && (previousGame !== game || consent !== PERFORMANCE_CONSENT));
}
