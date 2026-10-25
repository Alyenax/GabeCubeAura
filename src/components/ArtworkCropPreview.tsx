import type { RefObject } from "react";
import { artworkCropWindow, artworkPreviewMedia } from "../faceplate_artwork_gallery";
import type { FaceplateArtworkAsset } from "../api";

export function ArtworkCropPreview({ asset, cropX, cropY, guides, videoRef, onPlay, onPause, onError }: {
  asset: FaceplateArtworkAsset; cropX: number; cropY: number; guides: boolean;
  videoRef: RefObject<HTMLVideoElement | null>;
  onPlay: () => void; onPause: () => void; onError: () => void;
}) {
  const crop = artworkCropWindow(asset.width, asset.height, cropX, cropY);
  return <div style={{ position: "relative", height: 260, width: "100%", background: "#070a11" }}>
    {artworkPreviewMedia(asset.thumb, asset.animated) === "video"
      ? <video ref={videoRef} key={`${asset.kind}:${asset.id}`} src={asset.thumb}
        autoPlay muted loop playsInline preload="metadata" controls={false}
        onPlay={onPlay} onPause={onPause} onError={onError}
        style={{ display: "block", width: "100%", height: "100%", objectFit: "contain" }} />
      : <img src={asset.thumb} loading="lazy" referrerPolicy="no-referrer"
        style={{ display: "block", width: "100%", height: "100%", objectFit: "contain" }} />}
    {guides ? <svg aria-label="Faceplate crop boundaries" viewBox={`0 0 ${crop.sourceWidth} ${crop.sourceHeight}`}
      preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
      <path d={`M0 0H${crop.sourceWidth}V${crop.sourceHeight}H0Z M${crop.x} ${crop.y}v${crop.height}h${crop.width}v-${crop.height}Z`}
        fill="rgba(0,0,0,.45)" fillRule="evenodd" />
      {crop.horizontal ? <>
        <line x1={crop.x} x2={crop.x} y1={0} y2={crop.sourceHeight} stroke="#ff4545" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <line x1={crop.x + crop.width} x2={crop.x + crop.width} y1={0} y2={crop.sourceHeight} stroke="#ff4545" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </> : null}
      {crop.vertical ? <>
        <line x1={0} x2={crop.sourceWidth} y1={crop.y} y2={crop.y} stroke="#ff4545" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <line x1={0} x2={crop.sourceWidth} y1={crop.y + crop.height} y2={crop.y + crop.height} stroke="#ff4545" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </> : null}
    </svg> : null}
  </div>;
}
