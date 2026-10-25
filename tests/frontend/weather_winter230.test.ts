import assert from 'node:assert/strict';
import test from 'node:test';
import {WEATHER_CONFIGURATION_CONDITIONS, WEATHER_CONFIGURATION_VARIANTS, weatherConfigurationCondition, weatherVariantKey} from '../../src/weather_variants';
import {translate} from '../../src/i18n';

test('snow and storm expose independent native day/night choices and matching variants',()=>{
  for(const [condition,label,french] of [['snow','Snow','Neige'],['storm','Thunderstorm','Orage']] as const){
    const choices=WEATHER_CONFIGURATION_CONDITIONS.filter(row=>row.data.startsWith(condition));
    assert.deepEqual(choices.map(row=>row.data),[`${condition}_day`,`${condition}_night`]);
    for(const period of ['day','night'] as const){
      const choice=`${condition}_${period}` as const;
      assert.equal(choices.find(row=>row.data===choice)?.label,`${label} · ${period}`);
      assert.equal(translate(`${label} · ${period}`,'fr'),`${french} · ${period==='day'?'jour':'nuit'}`);
      assert.equal(weatherVariantKey(choice),`weather_${condition}${period==='night'?'_night':''}_variant`);
      assert.equal(WEATHER_CONFIGURATION_VARIANTS[choice].length,2);
      assert.equal(weatherConfigurationCondition(condition,period==='day'),choice);
    }
    assert.deepEqual(WEATHER_CONFIGURATION_VARIANTS[`${condition}_day`].map(row=>row.label),WEATHER_CONFIGURATION_VARIANTS[`${condition}_night`].map(row=>row.label));
  }
});
