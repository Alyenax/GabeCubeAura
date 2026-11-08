import {afterPatch,fakeRenderComponent,findModuleByExport,MenuItem,Navigation,type Patch} from '@decky/ui';
import {cloneElement,isValidElement,type ReactElement} from 'react';
import {getUILanguage} from './i18n';
import {addGameArtworkItem,artworkGamePath,GAME_ARTWORK_ITEM,menuAppId} from './game_artwork_menu';
import {menuItemLabel} from './game_artwork_menu';

/** Small native hook; an unknown Steam shape leaves its menus untouched. */
export function startGameArtworkMenu(onState?:(state:'ready'|'unavailable')=>void){
  let stopped=false,installed=false,faceplateAvailable=false,observedAt=0;
  // Status is already polled every five seconds. An interrupted poll cannot
  // keep a stale hardware-specific entry alive indefinitely.
  const canShow=()=>{const age=Date.now()-observedAt;return !stopped&&faceplateAvailable&&age>=0&&age<=15000;};
  const patches:Patch[]=[],timers:ReturnType<typeof setTimeout>[]=[];
  const tracked=new WeakMap<object,Set<string>>(),wrappers=new WeakMap<Function,Function>(),hints=new WeakMap<object,unknown>();
  let wrapperCount=0;
  const ownItem=(appid:number)=><MenuItem key={GAME_ARTWORK_ITEM} onSelected={()=>{
    if(canShow()){Navigation.CloseSideMenus();Navigation.Navigate(artworkGamePath(appid));}
  }}>{menuItemLabel(getUILanguage())}</MenuItem>;
  const visit=(value:any,hint?:unknown,depth=0):any=>{
    if(!canShow()||depth>12||!value)return value;
    if(Array.isArray(value)){
      const next=addGameArtworkItem(value,hint,ownItem);if(next!==value)return next;
      let changed=false;const children=value.map(item=>{const next=visit(item,hint,depth+1);changed ||=next!==item;return next;});
      return changed?children:value;
    }
    if(!isValidElement(value)||value.key===GAME_ARTWORK_ITEM)return value;
    const element=value as ReactElement<any>,props=element.props;
    const nextHint=menuAppId(props.children,props.overview?.appid??props.app?.appid??hint)??hint;
    hints.set(props,nextHint);
    let type:any=element.type;
    if(typeof type==='object'&&type!==null){
      if(typeof type.render==='function')track(type,'render');
      else if(typeof type.type==='function'){if(typeof type.type.prototype?.render==='function')track(type.type.prototype,'render');else track(type,'type');}
    }
    if(typeof type==='function'&&typeof type.prototype?.render==='function')track(type.prototype,'render');
    else if(typeof type==='function'){
      let wrapper=wrappers.get(type);
      if(!wrapper&&wrapperCount<80){const original=type;wrapper=function(this:unknown,...args:any[]){const result=original.apply(this,args);try{return visit(result,args[0]?.overview?.appid??args[0]?.app?.appid??hints.get(args[0]));}catch{return result;}};
        wrappers.set(type,wrapper);wrapperCount++;}
      if(wrapper)type=wrapper;
    }
    const children=visit(props.children,nextHint,depth+1);
    if(children===props.children&&type===element.type)return value;
    const copy=cloneElement(element,children===props.children?{}:{children});
    hints.set(copy.props,nextHint);
    return type===element.type?copy:{...copy,type};
  };
  function track(object:any,key:string){
    if(!object||typeof object[key]!=='function')return;
    const methods=tracked.get(object)??new Set<string>();if(methods.has(key))return;
    methods.add(key);tracked.set(object,methods);
    patches.push(afterPatch(object,key,function(this:any,_args,result){
      if(stopped)return result;
      try{return visit(result,_args[0]?.overview?.appid??_args[0]?.app?.appid??hints.get(_args[0])??hints.get(this?.props)??this?.props?.overview?.appid??this?.props?.app?.appid??result?._owner?.pendingProps?.overview?.appid);}catch{return result;}
    }));
  }
  const install=()=>{
    if(stopped||installed)return;
    try{
      const found=findModuleByExport((value:any)=>typeof value==='function'&&value.toString().includes('().LibraryContextMenu'));
      if(!found)return;
      for(const value of Object.values(found)){
        if(typeof value!=='function'||!value.toString().includes('navigator:'))continue;
        const menu=fakeRenderComponent(value)?.type;
        if(typeof menu?.prototype?.render==='function'){track(menu.prototype,'render');installed=true;onState?.('ready');return;}
      }
    }catch{/* Settings always retains a direct game picker if Steam changes. */}
  };
  install();for(const delay of [2000,8000,20000])timers.push(setTimeout(()=>{install();if(delay===20000&&!stopped&&!installed)onState?.('unavailable');},delay));
  return {get available(){return installed;},setFaceplateAvailable(available:boolean){
    if(!stopped){faceplateAvailable=available===true;observedAt=Date.now();}
  },stop(){stopped=true;faceplateAvailable=false;timers.forEach(clearTimeout);
    for(const patch of patches.reverse())try{if(!patch.hasUnpatched)patch.unpatch();}catch{/* Preserve other plugins' patches. */}
    patches.length=0;}};
}
