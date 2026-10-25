import type {ReactNode} from 'react';
import {useSettingsPresentation} from '../settings_presentation';
import {Disclosure} from './Disclosure';

/** Rare settings remain actionable, but do not fill the normal page. */
export function SettingsDetails({title,children}:{title:string;children:ReactNode}){
  return useSettingsPresentation()?<Disclosure title={title}>{children}</Disclosure>:<>{children}</>;
}
