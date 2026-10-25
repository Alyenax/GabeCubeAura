import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  artworkPreviewMedia,
  artworkCropWindow,
  artworkNeedsIdleGame,
  LIGHT_BAR_ARTWORK_ROUTE,
  LIGHT_BAR_SETTINGS_ROUTE,
  artworkResultLabel,
  takeArtworkNativeFocus,
} from "../../src/faceplate_artwork_gallery";

test("crop guides match the aligned 64 by 54 decoder window, not a guessed rectangle", () => {
  const wide = artworkCropWindow(1920, 620, 50, 50);
  assert.equal(wide.x, 52 * 1920 / 168);
  assert.equal(wide.width, 64 * 1920 / 168);
  assert.equal(wide.y, 0);
  assert.equal(wide.height, 620);
  assert.equal(wide.horizontal, true);
  assert.equal(wide.vertical, false);
  const square = artworkCropWindow(512, 512, 50, 50);
  assert.equal(square.y, 40);
  assert.equal(square.height, 432);
  assert.equal(square.horizontal, false);
  assert.equal(square.vertical, true);
  const portrait = artworkCropWindow(600, 900, -50, 150);
  assert.equal(portrait.x, 0);
  assert.equal(portrait.y + portrait.height, 900);
  assert.equal(portrait.width, 600);
  assert.equal(artworkCropWindow(64, 59, 50, 10).y, 0); // Python ties-to-even
  assert.equal(artworkCropWindow(64, 59, 50, 30).y, 2);
});

test("exact matrix sources keep their full frame and invalid source metadata is safe", () => {
  const full = artworkCropWindow(64, 54, 0, 100);
  assert.deepEqual([full.x, full.y, full.width, full.height], [0, 0, 64, 54]);
  const unknown = artworkCropWindow(0, NaN, NaN, NaN);
  assert.deepEqual([unknown.sourceWidth, unknown.sourceHeight, unknown.y], [64, 64, 5]);
});

test("animated generation needs an idle game; artwork colours and general routing have distinct routes", () => {
  assert.equal(artworkNeedsIdleGame("static"), false);
  for (const mode of ["animated", "pan", "unknown"]) assert.equal(artworkNeedsIdleGame(mode), true);
  assert.equal(LIGHT_BAR_ARTWORK_ROUTE, "/gabecubeaura/settings/artwork");
  assert.equal(LIGHT_BAR_SETTINGS_ROUTE, "/gabecubeaura/settings/routing");
});

test("Studio has one destination-specific draft, stable preparation focus and bounded receipt reads", () => {
  const source = readFileSync(new URL("../../src/index.tsx", import.meta.url), "utf8");
  const effect = source.slice(source.indexOf('const job = artworkState?.job;'), source.indexOf('}, [STUDIO_UX'));
  assert.ok(!effect.includes('Promise.all'));
  assert.ok(effect.includes('preparedIdentity.current !== preparationIdentity'));
  assert.ok(effect.includes('getPreparedFaceplateArtworkPreview'));
  assert.ok(effect.includes('getFaceplateArtworkDashboardPreview'));
  assert.ok(source.includes('!STUDIO_UX && selectedGame && !choosingGame'));
  const prepare = source.slice(source.indexOf('const prepare = async (apply'), source.indexOf('const chooseGame'));
  assert.ok(!prepare.includes('restoreArtworkFocus("adjust-image")'));
  assert.ok(prepare.includes('restoreArtworkFocus(prepareFocus.current)'));
  assert.ok(source.includes('const deadline = Date.now() + 120_000'));
  assert.ok(source.includes('next.routing.desired_content_key !== deliveryKey.current'));
  assert.ok(source.includes('Navigation.Navigate(LIGHT_BAR_ARTWORK_ROUTE)'));
});

test("SteamGridDB video previews use a controller-friendly external player", () => {
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.webm?size=small", true), "video");
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.mp4", true), "video");
});

test("animated image previews remain native while static thumbnails stay images", () => {
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.gif", true), "animated-image");
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.webp", true), "animated-image");
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.jpg", true), "image");
  assert.equal(artworkPreviewMedia("https://cdn.example/preview.webp", false), "image");
});

test("gallery position is human-readable and bounded", () => {
  assert.equal(artworkResultLabel(0, 8), "1 of 8");
  assert.equal(artworkResultLabel(99, 8), "8 of 8");
  assert.equal(artworkResultLabel(0, 0), "No artwork");
});

test("native focus walks nested Decky navigation nodes and takes the matching region", () => {
  const target = {} as Element;
  let focused = 0;
  const trees = [{
    Root: {
      m_rgChildren: [{
        m_rgChildren: [{
          Element: target,
          BTakeFocus: () => {
            focused += 1;
            return true;
          },
        }],
      }],
    },
  }];

  assert.equal(takeArtworkNativeFocus(target, trees), true);
  assert.equal(focused, 1);
  assert.equal(takeArtworkNativeFocus({} as Element, trees), false);
});
