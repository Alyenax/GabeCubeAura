export type ArtworkPreviewMedia = "video" | "animated-image" | "image";

export const LIGHT_BAR_ARTWORK_ROUTE = "/gabecubeaura/settings/artwork";
export const LIGHT_BAR_SETTINGS_ROUTE = "/gabecubeaura/settings/routing";

// Same cover-size alignment and integer window as steamgriddb._crop_cover.
// Coordinates are mapped back to the source so SVG/object-fit letterboxing
// cannot shift the guides. Python rounds exact halves to the even integer.
function pixelRound(value: number): number {
  const floor = Math.floor(value);
  return value - floor === .5 ? floor + (floor % 2) : Math.round(value);
}

export function artworkCropWindow(width: number, height: number, cropX: number, cropY: number) {
  width = width > 0 && Number.isFinite(width) ? Math.floor(width) : 64;
  height = height > 0 && Number.isFinite(height) ? Math.floor(height) : 64;
  const ratio = width / height;
  let decodedWidth = ratio >= 64 / 54 ? Math.max(64, Math.ceil(54 * ratio)) : 64;
  const decodedHeight = ratio >= 64 / 54 ? 54 : Math.max(54, Math.ceil(64 / ratio));
  decodedWidth = Math.ceil(decodedWidth / 4) * 4;
  const clamp = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(100, Math.trunc(value))) : 50;
  return {
    sourceWidth: width, sourceHeight: height,
    x: pixelRound((decodedWidth - 64) * clamp(cropX) / 100) * width / decodedWidth,
    y: pixelRound((decodedHeight - 54) * clamp(cropY) / 100) * height / decodedHeight,
    width: 64 * width / decodedWidth, height: 54 * height / decodedHeight,
    horizontal: decodedWidth > 64, vertical: decodedHeight > 54,
  };
}

export function artworkNeedsIdleGame(mode: string): boolean {
  return mode !== "static";
}

export type ArtworkNativeFocusNode = {
  Element?: Element;
  m_rgChildren?: ArtworkNativeFocusNode[];
  BTakeFocus?: () => boolean;
};

export type ArtworkNativeNavigationTree = {
  Root?: ArtworkNativeFocusNode;
};

export function artworkPreviewMedia(url: string, animated: boolean): ArtworkPreviewMedia {
  const path = String(url || "").split(/[?#]/, 1)[0].toLocaleLowerCase();
  if (/\.(webm|mp4)$/.test(path)) return "video";
  if (animated && /\.(gif|webp)$/.test(path)) return "animated-image";
  return "image";
}

export function artworkResultLabel(index: number, count: number): string {
  const safeCount = Math.max(0, Math.floor(count));
  if (!safeCount) return "No artwork";
  const safeIndex = Math.max(0, Math.min(safeCount - 1, Math.floor(index)));
  return `${safeIndex + 1} of ${safeCount}`;
}

export function takeArtworkNativeFocus(
  element: Element | null,
  trees: ArtworkNativeNavigationTree[],
): boolean {
  if (!element) return false;
  for (const tree of trees) {
    const pending = tree.Root ? [tree.Root] : [];
    while (pending.length) {
      const node = pending.pop();
      if (!node) continue;
      if (node.Element === element && typeof node.BTakeFocus === "function") {
        return Boolean(node.BTakeFocus());
      }
      if (Array.isArray(node.m_rgChildren)) pending.push(...node.m_rgChildren);
    }
  }
  return false;
}
