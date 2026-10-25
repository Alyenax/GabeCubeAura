import { gamepadDialogClasses, gamepadSliderClasses, quickAccessControlsClasses, gamepadTabbedPageClasses, findClassModule } from '@decky/ui';

/**
 * Steam owns these CSS module names. Resolve them through Decky's live class
 * registry rather than guessing a gamepaddialog_ prefix or a build hash.
 * Every selector is settings-scoped: the quick-access panel is not restyled.
 */
export function settingsClassSelector(classes: Record<string, string> | undefined, key: string): string {
  const tokens = classes?.[key]?.split(/\s+/).filter(Boolean) ?? [];
  if (!tokens.length) return `#gca-settings-root .gca-native-unavailable-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  return `#gca-settings-root ${tokens.map(token => `[class~="${token.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"]`).join('')}`;
}

const field = (key: string) => settingsClassSelector(gamepadDialogClasses, key);
const panel = (key: string) => settingsClassSelector(quickAccessControlsClasses, key);
// Valve's Gamepad PagedSettings stylesheet (not the desktop or controller-editor
// stylesheet with similarly named keys). Verified against the native renderer.
const sidebarClasses=findClassModule(module=>Boolean(module.ScaledChildren&&module.PagedSettingsDialog_PageContent));
const sidebar=(key:string)=>settingsClassSelector(sidebarClasses||undefined,key);
const tab=(key:string)=>settingsClassSelector(gamepadTabbedPageClasses,key);

export const SETTINGS_NATIVE = {
  field: field('Field'),
  fieldLeft: field('FieldLeftColumn'),
  // Present in Steam's registry and DOM even though @decky/ui 4.12.1 omits
  // FieldRightColumn from its static key union. Never substitute the inner
  // child: there are two additional native layout ancestors around it.
  fieldRight: field('FieldRightColumn'),
  fieldLabel: field('FieldLabel'),
  fieldLabelRow: field('FieldLabelRow'),
  fieldChildren: field('FieldChildrenInner'),
  fieldChildrenWithIcon: field('FieldChildrenWithIcon'),
  childrenWidthFixed: field('ChildrenWidthFixed'),
  childrenWidthGrow: field('ChildrenWidthGrow'),
  fieldDescription: field('FieldDescription'),
  controlsListChild: field('ControlsListChild'),
  background: field('BackgroundAnimation'),
  focusAnimation: field('focusAnimation'),
  panel: panel('PanelSection'),
  panelRow: panel('PanelSectionRow'),
  panelTitle: panel('PanelSectionTitle'),
  panelBackground: panel('BackgroundAnimation'),
  toggle: field('Toggle'),
  toggleRail: field('ToggleRail'),
  toggleSwitch: field('ToggleSwitch'),
  dropdownContents: field('DropDownControlButtonContents'),
  dropdownRow: field('DropDownRow'),
  sliderTrack: settingsClassSelector(gamepadSliderClasses,'SliderTrack'),
  sliderTrackDark: settingsClassSelector(gamepadSliderClasses,'SliderTrackDark'),
  sliderHandle: settingsClassSelector(gamepadSliderClasses,'SliderHandle'),
  sliderLabel: settingsClassSelector(gamepadSliderClasses,'LabelText'),
  sliderBackground: settingsClassSelector(gamepadSliderClasses,'BackgroundAnimation'),
  sidebarRoot:sidebar('PagedSettingsDialog'),
  sidebarColumn:sidebar('PagedSettingsDialog_PageListColumn'),
  sidebarList:sidebar('PagedSettingsDialog_PageList'),
  sidebarItem:sidebar('PagedSettingsDialog_PageListItem'),
  sidebarActive:sidebar('Active'),
  sidebarItemTitle:sidebar('PageListItem_Title'),
  sidebarScaled:sidebar('ScaledChildren'),
  sidebarContentColumn:sidebar('PagedSettingDialog_ContentColumn'),
  sidebarPage:sidebar('PagedSettingsDialog_PageContent'),
  sidebarTransition:sidebar('ContentTransition'),
  sidebarExit:sidebar('Exit'),
  tabPage:tab('GamepadTabbedPage'),
  tabHeader:tab('TabHeaderRowWrapper'),
  tabRow:tab('TabRow'),
  tabRowTabs:tab('TabRowTabs'),
  tabItem:tab('Tab'),
  tabTitle:tab('TabTitle'),
  tabSelected:tab('Selected'),
  tabGlyphs:tab('Glyphs'),
  tabContent:tab('TabContents'),
  tabScroll:tab('TabContentsScroll'),
  tabTransition:tab('ContentTransition'),
  tabExit:tab('Exit'),
} as const;
