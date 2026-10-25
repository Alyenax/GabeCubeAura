import * as Decky from "@decky/ui";
import { createElement, forwardRef, useSyncExternalStore,
  type ComponentPropsWithoutRef, type Ref, type ElementType, type ReactNode } from "react";
import { getUILanguage, subscribeUILanguage, translateUIProperties, type TextProperties } from "./i18n";

import { translateNode } from "./localized_nodes";
import {useSettingsHelp} from './settings_presentation';
export { Localized } from "./localized_nodes";

type LocalizationOptions = { untranslatedProps?: readonly string[]; untranslatedOptions?: boolean };


type SettingsNativeKind = 'section' | 'row' | 'field' | 'button';
type SettingsControl = 'action' | 'dropdown' | 'slider' | 'text' | 'toggle';

function localized<C extends ElementType>(Component: C, settingsKind?: SettingsNativeKind, settingsControl?: SettingsControl) {
  return forwardRef<unknown, ComponentPropsWithoutRef<C> & LocalizationOptions>((props, ref) => {
    const locale = useSyncExternalStore(subscribeUILanguage, getUILanguage, getUILanguage);
    const next = translateUIProperties(props as TextProperties, locale, (node) => translateNode(node, locale));
    const compact=useSettingsHelp((next.label ?? next.title) as ReactNode, next.description as ReactNode);
    if(compact && 'description' in next) next.description=undefined;
    if(compact && (settingsKind==='section'||settingsKind==='row')){
      // PanelSection belongs to the quick-access sidebar. It is only a visual
      // container, so full-page settings must not inherit its QAM dimensions.
      const children=Array.isArray(next.children)?next.children:[next.children];
      if(settingsKind==='row') return createElement('div',{className:'gca-native-row',ref},...children);
      return createElement(Decky.DialogControlsSection,{className:'gca-native-section',ref:ref as Ref<HTMLDivElement>,...{'aria-busy':next.spinner?true:undefined}},
        next.title?createElement(Decky.DialogControlsSectionHeader,{},next.title as ReactNode):null,
        next.spinner?createElement(Decky.SteamSpinner,{className:'gca-section-spinner',background:'transparent'}):null,...children);
    }
    if(compact && settingsControl && settingsControl!=='text'){
      // Public ItemProps, not CSS guesses: ButtonItem and DropdownItem use
      // childrenContainerWidth="min" by default. Combining that native mode
      // with a flex override can shrink an action to one letter per line.
      next.layout='inline';
      next.childrenContainerWidth=settingsControl==='toggle'?'min':'fixed';
    }
    // className is part of DialogButton's public API; no extra focus scope
    // or replacement is introduced.
    if(compact && settingsKind==='button') next.className=[next.className,'gca-native-button'].filter(Boolean).join(' ');
    // Keep static child arrays static for React, retaining existing keys and refs.
    const control=createElement(Component, { ...next, ref }, ...(Array.isArray(next.children)?next.children:[next.children]));
    // Item components do not promise to forward className. A nonfocusable
    // wrapper exposes their type without adding a gamepad-navigation scope.
    return compact && settingsKind && settingsKind!=='button'
      ? createElement('div',{className:`gca-native-${settingsKind}`,
          ...(settingsControl?{'data-gca-control':settingsControl}:{}),
          ...(Component===Decky.ToggleField?{'data-gca-toggle':'true','data-gca-checked':String(Boolean(next.checked))}:{})},control)
      : control;
  });
}

// Thin adapters preserve Decky's native controls and gamepad navigation.
export const ButtonItem = localized(Decky.ButtonItem,'field','action');
export const ConfirmModal = localized(Decky.ConfirmModal);
export const DialogButton = localized(Decky.DialogButton,'button');
export const DropdownItem = localized(Decky.DropdownItem,'field','dropdown');
export const Dropdown = localized(Decky.Dropdown);
export const Field = localized(Decky.Field,'field');
export const Focusable = localized(Decky.Focusable);
export const PanelSection = localized(Decky.PanelSection,'section');
export const PanelSectionRow = localized(Decky.PanelSectionRow,'row');
export const SidebarNavigation = localized(Decky.SidebarNavigation);
export const ScrollPanel = localized(Decky.ScrollPanel);
export const SliderField = localized(Decky.SliderField,'field','slider');
export const TextField = localized(Decky.TextField,'field','text');
export const ToggleField = localized(Decky.ToggleField,'field','toggle');
