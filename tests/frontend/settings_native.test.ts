import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement} from 'react';

function evaluate(file:string,globals:Record<string,unknown>){
  const source=readFileSync(new URL(file,import.meta.url),'utf8');
  const ast=ts.createSourceFile(file,source,99,true,ts.ScriptKind.TSX);
  const body=ast.statements.filter(n=>!ts.isImportDeclaration(n)&&!ts.isExportDeclaration(n)).map(n=>n.getText(ast)).join('\n');
  const context=vm.createContext({exports:{},...globals});
  vm.runInContext(ts.transpileModule(body,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
  return context.exports as any;
}

const names=['ButtonItem','ConfirmModal','DialogButton','DropdownItem','Dropdown','Focusable','PanelSection','PanelSectionRow','SidebarNavigation','ScrollPanel','SliderField','TextField','ToggleField'];
function adapter(compact:boolean){
  const Decky=Object.fromEntries([...names,'DialogControlsSection','DialogControlsSectionHeader'].map(name=>[name,`steam-${name}`]));
  return evaluate('../../src/localized_ui.tsx',{
    Decky,createElement,forwardRef:(fn:any)=>fn,
    useSyncExternalStore:(_subscribe:any,get:any)=>get(),subscribeUILanguage:()=>{},getUILanguage:()=> 'en',
    translateUIProperties:(props:any)=>({...props}),translateNode:(node:any)=>node,useSettingsHelp:()=>compact,
  });
}

test('settings native layout hooks do not alter quick-access controls or their refs/handlers',()=>{
  const controls=adapter(false),onClick=()=>{},onChange=()=>{},ref={current:null};
  for(const name of names){
    const control=controls[name]({label:'Original',description:'Original help',className:'existing',onClick,onChange,disabled:true,children:'Value'},ref);
    assert.equal(control.type,`steam-${name}`,name);
    assert.equal(control.props.description,'Original help',name);
    assert.equal(control.props.className,'existing',name);
    assert.equal(control.props.onClick,onClick,name);assert.equal(control.props.onChange,onChange,name);assert.equal(control.props.ref,ref,name);
  }
});

test('settings-only nonfocus wrappers retain native Steam control and original disabled behavior',()=>{
  const controls=adapter(true),onChange=()=>{},ref={current:null};
  for(const name of ['ButtonItem','DropdownItem','SliderField','TextField','ToggleField']){
    const tree=controls[name]({description:'Help',onChange,disabled:true,children:'Value'},ref);
    assert.equal(tree.type,'div',name);assert.match(tree.props.className,/^gca-native-(field|section|row)$/);
    assert.equal(tree.props.tabIndex,undefined);assert.equal(tree.props.onGamepadFocus,undefined);
    assert.equal(tree.props.children.type,`steam-${name}`);assert.equal(tree.props.children.props.onChange,onChange);
    assert.equal(tree.props.children.props.ref,ref);assert.equal(tree.props.children.props.disabled,true);
    assert.equal(tree.props.children.props.description,undefined);
  }
  const section=controls.PanelSection({title:'Title',children:'Contents'},ref);
  assert.equal(section.type,'steam-DialogControlsSection');assert.equal(section.props.className,'gca-native-section');
  assert.equal(section.props.children[0].type,'steam-DialogControlsSectionHeader');assert.equal(section.props.children[0].props.children,'Title');
  assert.equal(section.props.children[2],'Contents');assert.equal(section.props.ref,ref);
  const row=controls.PanelSectionRow({children:'Contents'},ref);
  assert.equal(row.type,'div');assert.equal(row.props.className,'gca-native-row');assert.equal(row.props.children,'Contents');
  assert.equal(row.props.tabIndex,undefined);assert.equal(row.props.ref,ref);
  const dialog=controls.DialogButton({className:'gca-tab',children:'Listen'},ref);
  assert.equal(dialog.type,'steam-DialogButton');assert.equal(dialog.props.className,'gca-tab gca-native-button');assert.equal(dialog.props.ref,ref);
  for(const checked of [false,true]){
    const toggle=controls.ToggleField({checked,onChange,disabled:false},ref);
    assert.equal(toggle.props['data-gca-toggle'],'true');assert.equal(toggle.props['data-gca-checked'],String(checked));
    assert.equal(toggle.props.children.props.checked,checked);assert.equal(toggle.props.children.props.onChange,onChange);
  }
});

test('settings fields choose the documented native inline fixed-width layout before styling',()=>{
  const controls=adapter(true);
  for(const [name,kind] of [['ButtonItem','action'],['DropdownItem','dropdown'],['SliderField','slider'],['ToggleField','toggle']]){
    const onChange=()=>{},tree=controls[name]({label:'A label',onChange,layout:'below',childrenContainerWidth:'min'});
    assert.equal(tree.props['data-gca-control'],kind,name);
    assert.equal(tree.props.children.props.layout,'inline',name);
    assert.equal(tree.props.children.props.childrenContainerWidth,kind==='toggle'?'min':'fixed',name);
    assert.equal(tree.props.children.props.onChange,onChange,name);
  }
  const text=controls.TextField({label:'City',value:'Paris'});
  assert.equal(text.props['data-gca-control'],'text');
  assert.equal(text.props.children.props.layout,undefined);
  assert.equal(text.props.children.props.childrenContainerWidth,undefined);
  // QAM and dialogs outside Settings retain every original native sizing prop.
  for(const name of ['ButtonItem','DropdownItem','SliderField','ToggleField']){
    const control=adapter(false)[name]({layout:'below',childrenContainerWidth:'max'});
    assert.equal(control.props.layout,'below');assert.equal(control.props.childrenContainerWidth,'max');
  }
});

test('settings section keeps title, content and native spinner without any focusable container',()=>{
  const Decky={PanelSection:'steam-PanelSection',DialogControlsSection:'steam-DialogControlsSection',DialogControlsSectionHeader:'steam-DialogControlsSectionHeader',SteamSpinner:'steam-Spinner'};
  const api=evaluate('../../src/localized_ui.tsx',{
    Decky,createElement,forwardRef:(fn:any)=>fn,
    useSyncExternalStore:(_subscribe:any,get:any)=>get(),subscribeUILanguage:()=>{},getUILanguage:()=> 'en',
    translateUIProperties:(props:any)=>({...props}),translateNode:(node:any)=>node,useSettingsHelp:()=>true,
  });
  const section=api.PanelSection({title:'Loading',spinner:true,children:'Child'});
  assert.equal(section.props['aria-busy'],true);
  assert.equal(section.props.children[1].type,'steam-Spinner');
  assert.equal(section.props.children[1].props.background,'transparent');
  assert.equal(section.props.children[2],'Child');
  assert.equal(section.props.tabIndex,undefined);
});

test('Steam CSS selectors resolve the actual runtime registry instead of assumed build prefixes',()=>{
  const api=evaluate('../../src/settings_native.ts',{
    findClassModule:()=>({ScaledChildren:'native_scaled',PagedSettingsDialog_PageContent:'native_page'}),
    gamepadTabbedPageClasses:{TabContentsScroll:'native_tabs_scroll'},
    gamepadSliderClasses:{SliderTrack:'new_slider_Track_2'},
    gamepadDialogClasses:{Field:'new_client_Control_17',FieldLeftColumn:'new_client_Left_42',FieldRightColumn:'new_client_Right_43',FieldChildrenInner:'new_client_Children_8',FieldChildrenWithIcon:'new_client_IconChildren_9',ChildrenWidthFixed:'new_client_Fixed_10',ChildrenWidthGrow:'new_client_Grow_11'},
    quickAccessControlsClasses:{PanelSection:'new_qam_Section_2',PanelSectionTitle:'new_qam_Title_3'},
  });
  assert.equal(api.SETTINGS_NATIVE.field,'#gca-settings-root [class~="new_client_Control_17"]');
  assert.equal(api.SETTINGS_NATIVE.fieldLeft,'#gca-settings-root [class~="new_client_Left_42"]');
  assert.equal(api.SETTINGS_NATIVE.fieldRight,'#gca-settings-root [class~="new_client_Right_43"]');
  assert.equal(api.SETTINGS_NATIVE.fieldChildren,'#gca-settings-root [class~="new_client_Children_8"]');
  assert.equal(api.SETTINGS_NATIVE.fieldChildrenWithIcon,'#gca-settings-root [class~="new_client_IconChildren_9"]');
  assert.equal(api.SETTINGS_NATIVE.childrenWidthFixed,'#gca-settings-root [class~="new_client_Fixed_10"]');
  assert.equal(api.SETTINGS_NATIVE.childrenWidthGrow,'#gca-settings-root [class~="new_client_Grow_11"]');
  assert.equal(api.SETTINGS_NATIVE.panelTitle,'#gca-settings-root [class~="new_qam_Title_3"]');
  assert.equal(api.SETTINGS_NATIVE.sliderTrack,'#gca-settings-root [class~="new_slider_Track_2"]');
  assert.equal(api.settingsClassSelector({},'Missing'),'#gca-settings-root .gca-native-unavailable-Missing');
  assert.equal(api.settingsClassSelector({Field:'one two'},'Field'),'#gca-settings-root [class~="one"][class~="two"]');
});
