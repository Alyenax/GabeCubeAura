import {faceplateBrightnessNotice} from '../faceplate_power';
import { useEffect, useRef, useState } from 'react';
import { callable } from '@decky/api';
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField, Localized } from '../localized_ui';

type Values = Record<string, string | number | boolean | number[]>;
interface Profile { id: string; name: string; values: Values }
interface State { active: string; temporary: boolean; profiles: Profile[]; current: Values }
const read = callable<[], State>('get_ambience_profiles');
const save = callable<[name: string, values: Values, identifier: string], State>('save_ambience_profile');
const activate = callable<[identifier: string], State>('activate_ambience_profile');
const remove = callable<[identifier: string], State>('delete_ambience_profile');
const home = ['steam', 'blackout', 'customization', 'performance', 'audio_sync', 'weather', 'controller'];
const game = [...home, 'artwork', 'screen_sync'];
const labels: Record<string, string> = { steam: 'Steam', blackout: 'Off', customization: 'Customization+', performance: 'Performance', audio_sync: 'Audio Sync', weather: 'Weather', controller: 'Controllers', artwork: 'Artwork', screen_sync: 'Screen Sync' };

/** No background polling, model or preview renderer. Edits retain control identity. */
export function AmbienceProfilesPanel() {
  const [state, setState] = useState<State | null>(null);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [draft, setDraft] = useState<Values>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void read().then(value => { if (alive.current) { setState(value); setDraft(value.current); } }).catch(() => { if (alive.current) setError('Profiles unavailable. Try reopening this page.'); });
    return () => { alive.current = false; };
  }, []);
  const run = async (action: () => Promise<State>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { const value = await action(); if (alive.current) setState(value); }
    catch (reason) { if (alive.current) setError(String(reason).replace(/^Error:\s*/, '')); }
    finally { if (alive.current) setBusy(false); }
  };
  const choose = (id: string) => {
    setSelected(id); setConfirmDelete(false);
    const item = state?.profiles.find(value => value.id === id);
    setName(item?.name ?? ''); setDraft(item?.values ?? state?.current ?? {});
  };
  const change = (key: string, value: Values[string]) => setDraft(old => ({ ...old, [key]: value }));
  const persist = (copy = false) => run(async () => {
    const value = await save(copy ? name.slice(0, 25) + ' copy' : name, draft, copy ? '' : selected);
    const item = value.profiles.find(profile => profile.id === (copy ? '' : selected))
      ?? value.profiles.find(profile => !state?.profiles.some(old => old.id === profile.id));
    if (alive.current && item) { setSelected(item.id); setName(item.name); setDraft(item.values); }
    return value;
  });
  const starter = async (kind: 'evening' | 'day') => {
    if (!state) return;
    await run(async () => {
      const value = await save(kind === 'evening' ? 'Evening' : 'Day', {
      ...state.current, night_mode_enabled: false,
      light_bar_day_brightness: kind === 'evening' ? Math.min(Number(state.current.light_bar_day_brightness), 9) : Number(state.current.light_bar_day_brightness),
      faceplate_brightness: kind === 'evening' ? Math.min(Number(state.current.faceplate_brightness), 35) : Number(state.current.faceplate_brightness),
      }, '');
      const item = value.profiles.find(profile => !state.profiles.some(old => old.id === profile.id));
      if (alive.current && item) { setSelected(item.id); setName(item.name); setDraft(item.values); }
      return value;
    });
  };
  return <PanelSection title="Ambience profiles">
    <PanelSectionRow><Localized>Temporary lighting profiles. Saved Home choices and per-game exceptions are kept. Critical protections always win.</Localized></PanelSectionRow>
    {state ? <>
      <PanelSectionRow><Localized>{state.temporary ? 'An ambience profile is active.' : 'Automatic mode · your usual settings.'}</Localized>
        {state.temporary ? <span translate="no"> {state.profiles.find(item => item.id === state.active)?.name}</span> : null}</PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Profile" selectedOption={selected} disabled={busy}
        rgOptions={[{ data: '', label: 'New · capture current settings' }, ...state.profiles.map(item => ({ data: item.id, label: <span translate="no">{item.name}</span> }))]}
        onChange={option => choose(String(option.data))} /></PanelSectionRow>
      <PanelSectionRow><TextField label="Profile name" value={name} disabled={busy} onChange={event => setName(event.currentTarget.value.slice(0, 32))} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem label={selected ? 'Save changes' : 'Save current settings as a profile'} disabled={busy || !name.trim()}
        onClick={() => void persist()}>Save</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Try selected profile" disabled={busy || !selected} onClick={() => void run(() => activate(selected))}>Try</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Restore automatic mode" disabled={busy || !state.temporary} onClick={() => void run(() => activate(''))}>Restore</ButtonItem></PanelSectionRow>
      {!state.profiles.some(item => item.name === 'Evening') ?
        <PanelSectionRow><ButtonItem label="Create Evening profile" disabled={busy} onClick={() => void starter('evening')}>Evening</ButtonItem></PanelSectionRow>
      : null}
      {!state.profiles.some(item => item.name === 'Day') ?
        <PanelSectionRow><ButtonItem label="Create Day profile" disabled={busy} onClick={() => void starter('day')}>Day</ButtonItem></PanelSectionRow>
      : null}
      <PanelSectionRow><ToggleField label="Edit profile details" checked={advanced} onChange={setAdvanced} /></PanelSectionRow>
      {advanced ? <>
        <PanelSectionRow><SliderField label="Light bar brightness" min={1} max={255} step={1} showValue disabled={busy}
          value={Number(draft.light_bar_day_brightness ?? state.current.light_bar_day_brightness)} onChange={value => change('light_bar_day_brightness', value)} /></PanelSectionRow>
        <PanelSectionRow><SliderField label="Faceplate brightness" min={5} max={100} step={1} showValue valueSuffix="%" disabled={busy}
          value={Number(draft.faceplate_brightness ?? state.current.faceplate_brightness)} onChange={value => change('faceplate_brightness', value)} /></PanelSectionRow>
        {faceplateBrightnessNotice(Number(draft.faceplate_brightness ?? state.current.faceplate_brightness)) ?
          <PanelSectionRow><Localized><small role="status">{faceplateBrightnessNotice(Number(draft.faceplate_brightness ?? state.current.faceplate_brightness))}</small></Localized></PanelSectionRow> : null}
        <PanelSectionRow><ToggleField label="Keep automatic night brightness" checked={Boolean(draft.night_mode_enabled)} disabled={busy}
          onChange={value => change('night_mode_enabled', value)} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="Home light bar" selectedOption={draft.home_display as string} disabled={busy}
          rgOptions={home.map(data => ({ data, label: labels[data] }))} onChange={option => change('home_display', String(option.data))} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="In-game light bar · per-game exceptions take priority" selectedOption={draft.game_display as string} disabled={busy}
          rgOptions={game.map(data => ({ data, label: labels[data] }))} onChange={option => change('game_display', String(option.data))} /></PanelSectionRow>
        <PanelSectionRow><ButtonItem label="Duplicate selected profile" disabled={busy || !selected}
          onClick={() => void persist(true)}>Duplicate</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem label={confirmDelete ? 'Confirm deletion · saved settings are kept' : 'Delete selected profile'} disabled={busy || !selected}
          onClick={() => { if (!confirmDelete) { setConfirmDelete(true); return; } void run(async () => { const value = await remove(selected); choose(''); return value; }); }}>Delete</ButtonItem></PanelSectionRow>
      </> : null}
    </> : null}
    {error ? <PanelSectionRow><div role="alert">{error}</div></PanelSectionRow> : null}
  </PanelSection>;
}
