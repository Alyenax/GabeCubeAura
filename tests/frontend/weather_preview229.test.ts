import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement, Fragment} from 'react';
import {WEATHER_CONFIGURATION_CONDITIONS, WEATHER_CONFIGURATION_VARIANTS, weatherConfigurationCondition, weatherVariantKey} from '../../src/weather_variants';

const source = readFileSync(new URL('../../src/index.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('index.tsx', source, 99, true, 4);
const panel = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'WeatherPanel')!;
function nodes(tree: any): any[] {return Array.isArray(tree) ? tree.flatMap(nodes) : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];}
function weather(connected: boolean) {
  const context = vm.createContext({React: {createElement, Fragment}, useState: (value: unknown) => [value, () => {}],
    WEATHER_CONFIGURATION_CONDITIONS, WEATHER_CONFIGURATION_VARIANTS, weatherConfigurationCondition, weatherVariantKey,
    WEATHER_ICON_STYLE_OPTIONS: [], WEATHER_TEMPERATURE_UNITS: [], formatAge: () => 'now',
    ...Object.fromEntries(['SettingsPart', 'PanelSection', 'PanelSectionRow', 'TextField', 'ButtonItem', 'ToggleField', 'DropdownItem', 'WeatherIconSetPreview', 'SettingsHelpText', 'FaceplateWeatherMatrixPreview', 'PalettePreview', 'Localized', 'FaceplateBrightnessSlider', 'FaceplateDiagnostics', 'SliderField'].map(name => [name, name])),
  });
  vm.runInContext(ts.transpileModule(panel.getText(ast) + '\nthis.render = WeatherPanel;', {
    compilerOptions: {jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText, context);
  return nodes(context.render({status: {weather: {condition: 'clear_day', is_day: true, colors: []}, faceplate: {available: connected}, weather_clear_day_variant: 0}, setStatus() {}}));
}
test('Weather animation mounts the matrix preview only while a Faceplate is connected', () => {
  assert.equal(weather(false).filter(node => node.type === 'FaceplateWeatherMatrixPreview').length, 0);
  assert.equal(weather(true).filter(node => node.type === 'FaceplateWeatherMatrixPreview').length, 1);
  for (const connected of [false, true]) {
    const buttons = weather(connected).filter(node => node.type === 'ButtonItem');
    assert(buttons.some(node => node.props.label === 'Preview this animation'));
    assert(!buttons.some(node => /Preview (?:night|day|warm) colours/.test(node.props.label)));
    assert(weather(connected).some(node => node.type === 'PalettePreview' && node.props.source === 'weather'));
  }
});
test('native quick panel and settings use the shared visibility-controlled colour stream', () => {
  const quick = readFileSync(new URL('../../src/components/CompactQuickPanel.tsx', import.meta.url), 'utf8');
  assert.match(quick, /<CompactLedPreview colors=\{frame\} active=\{active\}/);
  assert.match(source, /<LedPreviewActivity.Provider value=\{active\}>/);
  for (const channel of ['countdown', 'weather', 'customization', 'screen_sync', 'audio_sync', 'artwork', 'launch_artwork', 'performance']) {
    assert(source.includes(`<PalettePreview source="${channel}"`), channel);
  }
});
