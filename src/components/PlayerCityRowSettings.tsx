import {useState} from 'react';
import {DropdownItem, Localized, PanelSectionRow} from '../localized_ui';
import {setSetting} from '../api';
import type {Status} from '../types';
import {dashboardRowOptions, dashboardRowUsesControllers} from '../dashboard_settings';

export function PlayerCityRowSettings({status, setStatus, disabled = false}: {
  status: Status; setStatus: (status: Status) => void; disabled?: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const row = status.faceplate_player_city_row ?? 'count';
  const withoutPlayers = row === 'dashboard';
  const dashboardRow = status.faceplate_player_city_dashboard_row ?? 'controllers';
  const write = async (key: string, value: unknown) => {
    setSaving(true); setError('');
    try { setStatus(await setSetting(key, value)); }
    catch (reason) { setError(String(reason).replace(/^Error:\s*/, '')); }
    finally { setSaving(false); }
  };
  return <>
    <PanelSectionRow><DropdownItem label="Players City bottom row"
      description={withoutPlayers ? 'An active timer takes priority, then your saved row returns.' : row === 'count'
        ? 'Shows the exact player count. An active timer takes priority on the right.'
        : 'An active timer takes priority on the right. Player counts use k from 1,000 players.'}
      disabled={disabled || saving} selectedOption={row}
      rgOptions={[
        {data:'count',label:'Player Count Only'},
        {data:'controllers',label:'Players + controller'},
        {data:'session',label:'Players + session time'},
        {data:'achievements',label:'Players + achievements'},
        {data:'total',label:'Players + total playtime'},
        {data:'dashboard',label:'Without player count'},
      ]} onChange={async option => await write('faceplate_player_city_row', option.data)} /></PanelSectionRow>
    {withoutPlayers ? <>
      <PanelSectionRow><DropdownItem label="Bottom row content"
        disabled={disabled || saving} selectedOption={dashboardRow}
        rgOptions={dashboardRowOptions(true)}
        onChange={async option => await write('faceplate_player_city_dashboard_row', option.data)} /></PanelSectionRow>
    </> : null}
    {row === 'controllers' || (withoutPlayers && dashboardRowUsesControllers(dashboardRow)) ? <PanelSectionRow><DropdownItem label="Battery display"
        disabled={disabled || saving} selectedOption={status.faceplate_player_city_battery_style ?? 'percent'}
        rgOptions={[{data:'percent',label:'Percentage'},{data:'bar',label:'Battery bar'}]}
        onChange={async option => await write('faceplate_player_city_battery_style', option.data)} /></PanelSectionRow> : null}
    {error ? <PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow> : null}
  </>;
}
