import {useEffect, useState} from 'react';
import {Navigation} from '@decky/ui';
import {ButtonItem, DropdownItem, Localized, PanelSection, PanelSectionRow, ToggleField} from '../localized_ui';
import {getFaceplateDashboardBackgroundStatus, setSetting} from '../api';
import type {DashboardContent, Status} from '../types';
import {dashboardContext, updateDashboardContext, dashboardRowOptions, dashboardRowUsesControllers} from '../dashboard_settings';
import {useSettingsPresentation} from '../settings_presentation';

function DashboardContentSettings({content, game, saving, write, clockActive = false}: {
  content: DashboardContent; game: boolean; saving: boolean; clockActive?: boolean;
  write: (patch: Partial<DashboardContent>) => void;
}) {
  const rowVariant = game ? content.game_row ?? 'existing' : 'existing';
  const nativeRow = rowVariant === 'existing';
  const usesControllers = dashboardRowUsesControllers(nativeRow ? content.bottom_mode : rowVariant);
  return <>
    <PanelSectionRow><ToggleField label="Dashboard weather notch"
      description="Show the weather icon and temperature in this Dashboard."
      disabled={saving} checked={content.show_weather}
      onChange={value => write({show_weather: value})} /></PanelSectionRow>
    {content.show_weather ? <PanelSectionRow><DropdownItem label="Weather notch position"
      description="Turn off the Dashboard clock to move the weather notch. Your chosen position is kept."
      disabled={saving || clockActive} selectedOption={clockActive ? 'right' : content.weather_position ?? 'right'}
      rgOptions={[{data:'right',label:'Right'},{data:'center',label:'Centre'},{data:'left',label:'Left'}]}
      onChange={option => write({weather_position:option.data as DashboardContent['weather_position']})} /></PanelSectionRow> : null}
    <PanelSectionRow><ToggleField label="Show Dashboard bottom row"
      description="An active timer takes priority, then your saved row returns."
      disabled={saving} checked={content.show_bottom_row}
      onChange={value => write({show_bottom_row: value})} /></PanelSectionRow>
    {content.show_bottom_row ? <>
      <PanelSectionRow><DropdownItem label="Bottom row content"
        disabled={saving} selectedOption={nativeRow ? content.bottom_mode : rowVariant}
        rgOptions={dashboardRowOptions(game)} onChange={option => write(['next_hour','today','controllers'].includes(option.data)
          ? {bottom_mode: option.data as DashboardContent['bottom_mode'], ...(game ? {game_row:'existing' as const} : {})}
          : {game_row: option.data as DashboardContent['game_row']})} /></PanelSectionRow>
      {usesControllers ? <>
          <PanelSectionRow><DropdownItem label="Battery display"
            disabled={saving} rgOptions={[{data: 'percent', label: 'Percentage'}, {data: 'bar', label: 'Battery bar'}]}
            selectedOption={content.battery_style}
            onChange={option => write({battery_style: option.data as DashboardContent['battery_style']})} /></PanelSectionRow>
      </> : null}
      {game && !nativeRow && usesControllers ? <PanelSectionRow><Localized><div role="status">
        Combined rows show P1. Controllers shows both connected players.
      </div></Localized></PanelSectionRow> : null}
    </> : null}
  </>;
}

/** Live Dashboard choices take precedence over historical artwork metadata. */
export function FaceplateDashboardSettings({status, setStatus}: {
  status: Status; setStatus: (status: Status) => void;
}) {
  const presentation = useSettingsPresentation();
  const [background, setBackground] = useState<{appid: number; ready: boolean} | null>(null);
  const [libraryError, setLibraryError] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let alive = true;
    setBackground(null); setLibraryError(false);
    void getFaceplateDashboardBackgroundStatus().then(result => {
      if (alive) setBackground(result);
    }).catch(() => { if (alive) setLibraryError(true); });
    return () => { alive = false; };
  }, [status.faceplate_dashboard_home_appid]);
  const assigned = status.faceplate_dashboard_home_appid > 0
    && background?.appid === status.faceplate_dashboard_home_appid && background.ready;
  const missing = status.faceplate_dashboard_home_appid <= 0 || (background !== null && !assigned);
  const write = async (key: string, value: unknown) => {
    setSaving(true); setError('');
    try { setStatus(await setSetting(key, value)); }
    catch (reason) { setError(String(reason).replace(/^Error:\s*/, '')); }
    finally { setSaving(false); }
  };
  const writeContext = (context: 'home' | 'game', patch: Partial<DashboardContent>) =>
    void write('faceplate_dashboard_contexts', updateDashboardContext(status, context, patch));
  const open = (tab: 'display' | 'artwork') => {
    if (presentation) presentation.open({category: 'faceplate', tab});
    else { Navigation.CloseSideMenus(); Navigation.Navigate(`/gabecubeaura/settings/${tab === 'artwork' ? 'pixel-artwork' : 'pixel-settings'}`); }
  };
  return <>
    <div data-dashboard-context="home"><PanelSection title="Dashboard at Home">
      <PanelSectionRow><Localized><div role="status">
        These choices apply to both Dashboard Artwork and Dashboard Weather at Home. Choose the background in Display.
      </div></Localized></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Faceplate at Home" onClick={() => open('display')}>Open Display tab</ButtonItem></PanelSectionRow>
      {(status.faceplate.routing.routes.home === 'artwork-dashboard' || status.faceplate_dashboard_home_source === 'artwork') && (missing || libraryError) ? <PanelSectionRow><Localized><div role="status" style={{fontSize: '.85em', lineHeight: 1.5, color: '#ffd27a'}}>
        {libraryError
          ? 'The artwork library could not be checked. Open Artwork to check your saved backgrounds.'
          : 'Choose a saved Home artwork in the Artwork tab. Until it is ready, the Weather background is used. Select Artwork or Dashboard Artwork in Display.'}
      </div></Localized></PanelSectionRow> : null}
      <PanelSectionRow><ButtonItem label={assigned ? 'Change Home artwork' : 'Choose an Artwork Dashboard'}
        onClick={() => open('artwork')}>Open Artwork tab</ButtonItem></PanelSectionRow>
      {error ? <PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow> : null}
      <PanelSectionRow><ToggleField label="Home Dashboard Clock"
        description="Applies to Dashboard Artwork and Dashboard Weather at Home. Off by default. Updating the clock requires new images."
        disabled={saving} checked={status.faceplate_dashboard_show_clock ?? false}
        onChange={value => void write('faceplate_dashboard_show_clock', value)} /></PanelSectionRow>
      {status.faceplate_dashboard_clock_choice === 'legacy-unreviewed' ? <PanelSectionRow><Localized><div role="status">
        Your previous clock is kept. Choose whether to keep updating it or turn it off; your artwork library is unchanged.
        <ButtonItem label="Keep clock enabled" disabled={saving} onClick={() => void write('faceplate_dashboard_show_clock', true)}>Keep</ButtonItem>
        <ButtonItem label="Turn clock off" disabled={saving} onClick={() => void write('faceplate_dashboard_show_clock', false)}>Turn off</ButtonItem>
      </div></Localized></PanelSectionRow> : null}
      {status.faceplate_dashboard_show_clock ? <>
        <PanelSectionRow><DropdownItem label="Dashboard clock"
          disabled={saving} rgOptions={[{data: '24h', label: '24-hour · 21:48'}, {data: '12h', label: '12-hour · 9:48 PM'}]}
          selectedOption={status.faceplate_dashboard_clock_format}
          onChange={option => void write('faceplate_dashboard_clock_format', option.data)} /></PanelSectionRow>
        {!dashboardContext(status, 'home').show_weather ? <PanelSectionRow><DropdownItem label="Dashboard clock position"
          disabled={saving} rgOptions={[{data: 'left', label: 'Left'}, {data: 'center', label: 'Centre'}, {data: 'right', label: 'Right'}]}
          selectedOption={status.faceplate_dashboard_clock_position}
          onChange={option => void write('faceplate_dashboard_clock_position', option.data)} /></PanelSectionRow> : null}
      </> : null}
      <DashboardContentSettings content={dashboardContext(status, 'home')} game={false} saving={saving} clockActive={Boolean(status.faceplate_dashboard_show_clock)}
        write={patch => writeContext('home', patch)} />
    </PanelSection></div>
    <div data-dashboard-context="game"><PanelSection title="Dashboard in game">
      <PanelSectionRow><Localized><div role="status">
        These choices apply only in game, to both Weather and Artwork Dashboards. Home keeps its own settings.
      </div></Localized></PanelSectionRow>
      <DashboardContentSettings content={dashboardContext(status, 'game')} game saving={saving}
        write={patch => writeContext('game', patch)} />
      {error ? <PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow> : null}
    </PanelSection></div>
  </>;
}
