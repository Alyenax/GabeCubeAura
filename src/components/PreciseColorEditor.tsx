import { useEffect, useState } from "react";
import { showModal } from "@decky/ui";
import { ButtonItem, ConfirmModal, SliderField, TextField } from "../localized_ui";
import { hslStringToRgb, rgbToHsl } from "../performance";
import type { RGB } from "../types";

export function OpaqueColorPickerModal({ title, color, closeModal, onConfirm }: {
  title: string;
  color: RGB;
  closeModal: () => void;
  onConfirm: (color: RGB) => void;
}) {
  const [initialHue, initialSaturation, initialLightness] = rgbToHsl(color);
  const [hue, setHue] = useState(initialHue);
  const [saturation, setSaturation] = useState(initialSaturation);
  const [lightness, setLightness] = useState(initialLightness);
  const [selected, setSelected] = useState<RGB>(color);
  const applyHsl = (h: number, s: number, l: number) => setSelected(hslStringToRgb(`hsl(${h}, ${s}%, ${l}%)`) ?? selected);
  const canonicalHex = `#${selected.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
  const [hexText, setHexText] = useState(canonicalHex);
  useEffect(() => setHexText(canonicalHex), [canonicalHex]);
  return <ConfirmModal strTitle={title} strOKButtonText="Use colour" strCancelButtonText="Cancel"
    onCancel={closeModal} onOK={() => { onConfirm(selected); closeModal(); }}>
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ width: 38, height: 38, borderRadius: 5,
          background: `rgb(${selected.join(", ")})`, boxShadow: "0 0 0 1px rgba(255,255,255,.45)" }} />
        <span style={{ opacity: .78, fontSize: ".8em" }}>Opaque RGB colour · no alpha channel on the LED hardware.</span>
      </div>
      <TextField label="Hex" value={hexText} description="Exact #RRGGBB colour"
        onChange={(event) => {
          const next = event.currentTarget.value.toUpperCase();
          setHexText(next);
          const match = /^#?([0-9A-F]{6})$/.exec(next);
          if (!match) return;
          const rgb: RGB = [
            parseInt(match[1].slice(0, 2), 16),
            parseInt(match[1].slice(2, 4), 16),
            parseInt(match[1].slice(4, 6), 16),
          ];
          setSelected(rgb);
          const [nextHue, nextSaturation, nextLightness] = rgbToHsl(rgb);
          setHue(nextHue);
          setSaturation(nextSaturation);
          setLightness(nextLightness);
        }} />
      <SliderField label="Hue" value={hue} min={0} max={360} step={1} showValue
        onChange={value => { setHue(value); applyHsl(value, saturation, lightness); }} />
      <SliderField label="Saturation" value={saturation} min={0} max={100} step={1} showValue valueSuffix="%"
        onChange={value => { setSaturation(value); applyHsl(hue, value, lightness); }} />
      <SliderField label="Lightness" value={lightness} min={0} max={100} step={1} showValue valueSuffix="%"
        onChange={value => { setLightness(value); applyHsl(hue, saturation, value); }} />
    </div>
  </ConfirmModal>;
}

export function ColorChoice({ label, color, onClick, disabled = false }: {
  label: string;
  color: [number, number, number];
  onClick: () => void;
  disabled?: boolean;
}) {
  const cssColor = `rgb(${color.join(", ")})`;
  const hexColor = `#${color.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
  return <ButtonItem label={label} description={hexColor} onClick={onClick} disabled={disabled}>
    <span style={{
      display: "inline-block",
      width: 28,
      height: 28,
      borderRadius: 5,
      background: cssColor,
      boxShadow: "0 0 0 1px rgba(255,255,255,.45)",
    }} />
  </ButtonItem>;
}

export function PreciseColorEditor({ label, color, onChange, disabled = false }: {
  label: string;
  color: RGB;
  onChange: (color: RGB) => void;
  disabled?: boolean;
}) {
  const choose = () => {
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<OpaqueColorPickerModal title={label} color={color}
      closeModal={() => modal?.Close()} onConfirm={onChange} />);
  };
  return <ColorChoice label={label} color={color} onClick={choose} disabled={disabled} />;
}
