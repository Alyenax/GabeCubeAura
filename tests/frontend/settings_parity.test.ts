import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
const baseline=JSON.parse(readFileSync(new URL('../fixtures/lab158_settings_contract.json',import.meta.url),'utf8'));
const ast=ts.createSourceFile('index.tsx',source,99,true,4),printer=ts.createPrinter({removeComments:true});
type Control={owner:string;tag:string;label?:string;onChange?:string;onClick?:string;[key:string]:string|undefined};
const controls:Control[]=[];
function collect(node:ts.Node,owner=''){
  if(ts.isFunctionDeclaration(node)&&node.name)owner=node.name.text;
  if(ts.isJsxSelfClosingElement(node)||ts.isJsxOpeningElement(node)){
    const tag=node.tagName.getText(ast);
    if(['ToggleField','DropdownItem','SliderField','TextField','ButtonItem','PreciseColorEditor','ColorChoice'].includes(tag)){
      const field:Control={owner,tag};for(const prop of node.attributes.properties)if(ts.isJsxAttribute(prop)&&['label','min','max','step','rgOptions','onChange','onClick'].includes(prop.name.text)&&prop.initializer)field[prop.name.text]=printer.printNode(ts.EmitHint.Unspecified,prop.initializer,ast).replace(/\s+/g,' ').trim();controls.push(field);
    }
  }ts.forEachChild(node,child=>collect(child,owner));
}collect(ast);
test('approved compact panel replaces the old QAM; settings title remains native',()=>{
  const start=source.indexOf('function Content(');
  const quick=source.slice(source.indexOf('{page === "quick" ? <>',start),source.indexOf('{page !== "quick" && status.thermal_protection.active',start)).trim();
  assert.match(quick,/<CompactQuickPanel active={active} status={status} setStatus={setStatus} colors={shownColors\?\?\[\]}/);
  assert.doesNotMatch(quick,/QuickZone|QuickStatusCard|PerformanceReadout/);
  const title=source.slice(source.indexOf('titleView: <'),source.indexOf('content: <Content />'));
  assert.match(title,/gca-compact-title/);assert.match(title,/<QuickSettingsAction \/>/);
});
test('every existing native control retains its callback and numeric limits except explicit navigation changes',()=>{
  assert.equal(baseline.controls.length,214);
  const navigationOwners=new Set(['SettingsGroup','LegacySettingsPage']);
  const missing:string[]=[];
  const dashboard=readFileSync(new URL('../../src/components/FaceplateDashboardSettings.tsx',import.meta.url),'utf8');
  const dashboardDefaults=readFileSync(new URL('../../src/dashboard_settings.ts',import.meta.url),'utf8');
  for(const field of baseline.controls as Control[]){
    if(navigationOwners.has(field.owner)||field.owner==='SettingsPageEnd')continue;
    // Owner explicitly retired this calibration UI in beta6 / Lab248.
    if(field.owner==='HifiCrestLab'||(field.owner==='Content'&&field.label==='"Show Hi-Fi Crest tuning"')){
      assert(!controls.some(item=>item.owner===field.owner&&item.label===field.label),'Retired tuning control must be absent');
      continue;
    }
    // User retired the entire TW3/StripMine Compatibility panel in Lab243.
    if(field.owner==='CompatibilityPanel')continue;
    // User-requested removal: Weather has one preview for the chosen animation.
    if(field.owner==='WeatherPanel'&&['"Preview night colours"','"Preview warm colours"'].includes(field.label??''))continue;
    // Lab167 explicitly replaces this quick-panel switch, not a settings feature.
    if(field.owner==='Content'&&field.label==='"Enable GabeCubeAura"')continue;
    if(field.owner==='Content'&&['"Send diagnostic report now"','"Send crash diagnostics automatically"','"Connect GitHub"','"Disconnect GitHub"','"Open GitHub device authorization"','"I authorized this device"','"Disconnect Private Lab"','"Open last private diagnostic"','"Return to Lab 114"','"Valid package"','"Checksum mismatch"','"Rollback rehearsal"','"Export test report"'].includes(field.label??''))continue;
    // Export is now a native component with progress, path and error feedback.
    if(field.owner==='Content'&&field.label==='"Export configuration JSON"'){
      assert.match(source,/<ConfigurationExportSettings disabled=\{configurationBusy\} onBusyChange=\{setConfigurationBusy\}/);
      const exporter=readFileSync(new URL('../../src/components/ConfigurationExportSettings.tsx',import.meta.url),'utf8');
      assert.match(exporter,/label="Export configuration JSON"/);assert.match(exporter,/await exportConfiguration\(\)/);continue;
    }
    // Dashboard controls moved as one group in Lab199. Their persisted keys
    // remain, while callbacks now share pending/error handling and native links.
    if(field.owner==='Content'&&/faceplate_dashboard_/.test((field.onChange??'')+(field.onClick??''))){
      for(const key of ((field.onChange??'')+(field.onClick??'')).match(/faceplate_dashboard_[a-z_]+/g)??[])assert((dashboard+dashboardDefaults).includes(key),key);
      continue;
    }
    if(field.owner==='Content'&&field.label==='"Choose an Artwork Dashboard"'){
      assert.match(dashboard,/presentation.open\(\{category: 'faceplate', tab\}\)/);continue;
    }
    // Lab174 localizes the language-switch label; its callback/value is unchanged.
    const label=field.label==='"Français / English"'?'"French interface"':field.label;
    const matches=controls.filter(item=>item.owner===field.owner&&item.tag===field.tag&&item.label===label);
    if(!matches.length){missing.push(`${field.owner}/${field.label}`);continue;}
    for(const key of ['min','max','step'])assert(matches.some(item=>item[key]?.replaceAll('actionFailed','console.warn')===field[key]),`${field.label}/${key}`);
    for(const key of ['onChange','onClick'])if(field[key]){
      if(key==='onChange'&&((field.owner==='PixelStudioWeatherCatalog'&&field.label==='"Weather condition"')
          ||(field.owner==='WeatherPanel'&&field.label==='"Condition to configure"'))){
        assert(matches.some(item=>item.onChange?.replace('WeatherConfigurationCondition','WeatherCondition')===field.onChange),
          'Rain day/night extend the configuration choice while preserving the native callback');continue;
      }
      // City has one editor in Weather now, linked from global brightness.
      if(field.owner==='LightBarBrightness'&&field.label?.includes('Change city'))continue;
      if(field.owner==='CountdownPanel'&&field.label==='"Personal limit"'&&key==='onClick'){
        assert(matches.some(item=>item.onClick==='{startTimer}'),'Lab164 explicit power confirmation handler');continue;
      }
      if(field.owner==='Content'&&['"Faceplate at Home"','"Faceplate in game"'].includes(field.label??'')&&key==='onChange'){
        assert(matches.some(item=>item.onChange?.includes('changeFaceplateRoute')),'Display keeps the native route callback with Home parity');continue;
      }
      assert(matches.some(item=>item[key]?.replaceAll('actionFailed','console.warn')===field[key]),`${field.owner}/${field.label}/${key}`);
    }
  }
  assert.deepEqual(missing,[]);
});
test('all hardware options and complete effect catalogues remain in the native sources',()=>{
  for(const name of ['HOME_DISPLAY_OPTIONS','GAME_DISPLAY_OPTIONS','DISPLAY_PRESET_OPTIONS','FACEPLATE_HOME_OPTIONS','FACEPLATE_GAME_OPTIONS','CUSTOMIZATION_PATTERN_OPTIONS','LAUNCH_ARTWORK_PATTERN_OPTIONS','WEATHER_CONFIGURATION_VARIANTS','CONTROLLER_VARIANTS','EVENT_VARIANTS'])assert(source.includes(name),name);
  assert.doesNotMatch(source,/artStage|updateStage|_microTest|mockup-only|gca-simple-catalog/);
  assert.match(source,/new Set|SETTINGS_ALIASES/);
});
