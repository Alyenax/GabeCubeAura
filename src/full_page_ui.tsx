import {DialogControlsSection,DialogControlsSectionHeader,SteamSpinner} from '@decky/ui';
import type {ReactNode} from 'react';

/** Full-page containers, without the quick-access menu's outer gutters. */
export function FullPageSection({title,spinner,children}:{title?:ReactNode;spinner?:boolean;children:ReactNode}){
  return <DialogControlsSection>{title?<DialogControlsSectionHeader>{title}</DialogControlsSectionHeader>:null}{spinner?<SteamSpinner/>:null}{children}</DialogControlsSection>;
}
export function FullPageRow({children}:{children:ReactNode}){return <>{children}</>;}
