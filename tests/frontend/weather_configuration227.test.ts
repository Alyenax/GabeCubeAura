import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {WEATHER_CONFIGURATION_CONDITIONS, WEATHER_CONFIGURATION_VARIANTS, weatherConfigurationCondition, weatherVariantKey} from '../../src/weather_variants';
import {translate} from '../../src/i18n';

test('rain has two configuration entries with independent persisted selections',()=>{
  const rain=WEATHER_CONFIGURATION_CONDITIONS.filter(row=>row.data.startsWith('rain'));
  assert.deepEqual(rain,[{data:'rain_day',label:'Rain · day'},{data:'rain_night',label:'Rain · night'}]);
  assert.equal(weatherVariantKey('rain_day'),'weather_rain_variant');
  assert.equal(weatherVariantKey('rain_night'),'weather_rain_night_variant');
  for(const condition of ['rain_day','rain_night'] as const){
    assert.deepEqual(WEATHER_CONFIGURATION_VARIANTS[condition].map(row=>row.label),['Bluewater','Pearl rain']);
    assert.equal(translate(rain.find(row=>row.data===condition)!.label,'fr'),condition==='rain_day'?'Pluie · jour':'Pluie · nuit');
  }
  assert.equal(weatherConfigurationCondition('rain',false),'rain_night');
  assert.equal(weatherConfigurationCondition('rain',true),'rain_day');
  assert.equal(weatherConfigurationCondition('rain',null),'rain_day');
  assert.equal(weatherConfigurationCondition('cloud_night',false),'cloud_night');
});

test('both native configuration selectors and their preview use explicit phase choices',()=>{
  const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const catalog=source.slice(source.indexOf('function PixelStudioWeatherCatalog('),source.indexOf('function WeatherPanel('));
  const settings=source.slice(source.indexOf('function WeatherPanel('),source.indexOf('\nfunction ',source.indexOf('function WeatherPanel(')+15));
  for(const section of [catalog,settings]){
    assert.match(section,/rgOptions=\{WEATHER_CONFIGURATION_CONDITIONS\}/);
    assert.match(section,/weatherVariantKey\(/);
    assert.match(section,/FaceplateWeatherMatrixPreview/);
    assert.match(section,/condition=\{(?:condition|previewCondition)\}/);
  }
  assert.match(settings,/previewWeather\(condition, variant, weatherVisualTheme\)/);
});
