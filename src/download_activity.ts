export function downloadOverviewActive(overview: unknown): boolean {
  const updateState = (overview as { update_state?: unknown } | null)?.update_state;
  return Boolean(updateState && updateState !== "None");
}

type SteamDownloadItem = {
  active?: unknown;
  completed?: unknown;
  deferred_time?: unknown;
};

type SteamDownloadItemBatch = {
  item_data?: unknown;
};

export function downloadItemsActive(downloadItems: unknown): boolean {
  if (!Array.isArray(downloadItems)) return false;
  return downloadItems.some((rawBatch) => {
    const items = (rawBatch as SteamDownloadItemBatch | null)?.item_data;
    if (!Array.isArray(items)) return false;
    return items.some((rawItem) => {
      const item = rawItem as SteamDownloadItem | null;
      const deferred = Number(item?.deferred_time ?? 0);
      return Boolean(
        item?.active === true
        && item.completed !== true
        && Number.isFinite(deferred)
        && deferred <= 0
      );
    });
  });
}

export type DownloadActivitySource = "overview" | "items";

export type DownloadActivityDecision = {
  active: boolean;
  source: DownloadActivitySource;
};

export function resolveDownloadActivity(
  overviewActive: boolean,
  itemsActive: boolean,
  itemsSeen: boolean,
): DownloadActivityDecision {
  // The item replay carries the fields that distinguish a live transfer from
  // queued or deferred work. Once Steam has supplied it, a broad overview
  // state must not overwrite that more precise answer merely because its
  // callback happened to arrive last.
  return itemsSeen
    ? { active: itemsActive, source: "items" }
    : { active: overviewActive, source: "overview" };
}
