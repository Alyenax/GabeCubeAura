import {gamepadSliderClasses} from '@decky/ui';

/** Paint the focused row, never resize/reposition Steam's native slider.
 * Steam can focus the field, slider scope or an editable value. :focus-within
 * covers DOM/keyboard focus, the classes cover gamepad navigation separately.
 */
export function sliderFocusCSS(wrapper:string,accent:string,surface:string,underline=true):string{
  const disabled=gamepadSliderClasses?.Disabled?.split(/\s+/).filter(Boolean)
    .map(token=>`[class~="${token.replace(/"/g,'\\"')}"]`).join('')||'.gca-slider-unavailable-disabled';
  const enabled=`${wrapper}:not(:has(${disabled},[aria-disabled="true"],:disabled))`;
  return `${enabled}:is(:focus-within,:has(.gpfocus,.gpfocuswithin,:focus-visible)){background:${surface}!important;box-shadow:${underline?`inset 0 -2px 0 ${accent}`:'none'}!important}`;
}
