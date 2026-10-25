import assert from "node:assert/strict";
import test from "node:test";
import { isValidElement, type ReactElement } from "react";
import { ArtworkCropPreview } from "../../src/components/ArtworkCropPreview";
import type { FaceplateArtworkAsset } from "../../src/api";

function descendants(node: unknown): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  return [node, ...descendants(node.props.children)];
}

function preview(width: number, height: number, guides = true) {
  const asset: FaceplateArtworkAsset = { id: 1, kind: "hero", animated: false,
    width, height, author: "", url: "https://example.test/source.png", thumb: "https://example.test/source.png" };
  return descendants(ArtworkCropPreview({ asset, cropX: 50, cropY: 50, guides,
    videoRef: { current: null }, onPlay() {}, onPause() {}, onError() {} }));
}

test("wide and portrait sources show exactly two red boundaries over one contained image", () => {
  for (const [width, height, horizontal] of [[1920, 620, true], [600, 900, false]] as const) {
    const tree = preview(width, height);
    const lines = tree.filter(node => node.type === "line");
    assert.equal(lines.length, 2);
    assert.equal(tree.filter(node => node.type === "img").length, 1);
    assert.equal(tree.filter(node => node.type === "video").length, 0);
    assert.equal(tree.find(node => node.type === "svg")?.props.preserveAspectRatio, "xMidYMid meet");
    for (const line of lines) {
      assert.equal(line.props.stroke, "#ff4545");
      assert.equal(line.props.vectorEffect, "non-scaling-stroke");
      assert.equal(horizontal ? line.props.x1 : line.props.y1, horizontal ? line.props.x2 : line.props.y2);
    }
  }
});

test("crop overlay never intercepts interaction and disappears outside image adjustment", () => {
  const overlay = preview(512, 512).find(node => node.type === "svg");
  assert.equal((overlay?.props.style as Record<string, unknown>).pointerEvents, "none");
  assert.equal(preview(512, 512, false).filter(node => node.type === "svg").length, 0);
});
