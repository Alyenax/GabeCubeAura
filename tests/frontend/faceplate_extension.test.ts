import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {translate} from '../../src/i18n';
import {GAME_DISPLAY_OPTIONS} from '../../src/game_display_options';

const ui = readFileSync(new URL('../../src/index.tsx', import.meta.url), 'utf8');

test('source extension is an exclusive Home/in-game choice with inherited game overrides', () => {
  for (const name of ['HOME_DISPLAY_OPTIONS']) {
    const options = ui.slice(ui.indexOf(`const ${name}`), ui.indexOf('];', ui.indexOf(`const ${name}`)));
    assert.match(options, /data: "faceplate_extension", label: "Faceplate image extension"/);
  }
  assert(GAME_DISPLAY_OPTIONS.some(option=>option.data==='faceplate_extension'));
  assert.match(ui, /data: "inherit", label: "Use in-game default" }, \.\.\.gameDisplayOptions\(status.faceplate.available, status.display_override\)/);
  assert.match(ui, /setSetting\("faceplate_extension_mapping", String\(option.data\)\)/);
  assert.match(ui, /data: "bottom", label: "Bottom edge"/);
  assert.match(ui, /data: "whole", label: "Whole image"/);
  assert.match(ui, /selectedOption={status.faceplate_extension_mapping \?\? "bottom"}/);
});

test('preview reads only the cached 17-RGB status and never creates image capture or a timer', () => {
  const palette = ui.slice(ui.indexOf('const baseShownColors'), ui.indexOf('const shownColors'));
  assert.match(palette, /startsWith\("faceplate-extension:"\).*status.faceplate_extension\?\.colours/);
  assert.doesNotMatch(palette, /Canvas|<video|setInterval|fetch\(|getStatus|sampleArtwork/);
  assert.match(ui, /<CompactQuickPanel active={active} status={status} setStatus={setStatus} colors={shownColors\?\?\[\]}/);
});

test('extension saturation is a native live slider with no GIF job or brightness setter', () => {
  const start = ui.indexOf('<SliderField label="Extension colour saturation"');
  const slider = ui.slice(start, ui.indexOf('</PanelSectionRow>', start));
  assert.match(slider, /value={status.faceplate_extension_saturation \?\? 100}/);
  assert.match(slider, /min=\{0\} max=\{250\} step=\{5\} showValue valueSuffix="%"/);
  assert.match(slider, /setSetting\("faceplate_extension_saturation", value\)/);
  assert.doesNotMatch(slider, /prepare|encode|compile|setFaceplate|set.*brightness|fetch\(/);
  assert.equal(translate('Extension colour saturation', 'fr'), 'Saturation du prolongement');
});

test('game light bar shortcut opens the exact Effects artwork-colours destination', () => {
  assert.match(ui, /onOpenGame=\{\(\) => \{ Navigation.CloseSideMenus\(\); Navigation.Navigate\(LIGHT_BAR_ARTWORK_ROUTE\); \}\}/);
});

test('copy clearly excludes Dashboard overlays and does not claim animated frame synchronisation', () => {
  assert.match(ui, /original image before Dashboard text and its bottom row/);
  assert.match(ui, /stable average colours, not frame-synchronised motion/);
  assert.match(ui, /Global brightness and priority alerts are unchanged/);
  assert.match(ui, /Steam Players City without its counter/);
  assert.match(ui, /When the Faceplate is unavailable, the light bar uses current-game Artwork/);
});

test('projection settings and status are translated in French without changing stored identifiers', () => {
  for (const [en, fr] of [
    ['In-game light bar', 'Barre lumineuse en jeu'],
    ['Waiting for Gamescope: source unavailable', 'En attente de Gamescope: source unavailable'],
    ['Faceplate image extension', 'Prolongement de l’image faceplate'],
    ['Faceplate image projection', 'Projection de l’image faceplate'],
    ['Bottom edge', 'Bord inférieur'], ['Whole image', 'Image entière'],
    ['Original background · stable colours', 'Fond original · couleurs stables'],
    ['Preparing source colours…', 'Préparation des couleurs du fond…'],
  ]) assert.equal(translate(en, 'fr'), fr);
});
