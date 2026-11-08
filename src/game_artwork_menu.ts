/** Steam menu identity comes from this menu, never the running game or a default ID. */
export const GAME_ARTWORK_ROUTE='/gabecubeaura/faceplate-artwork';
export const GAME_ARTWORK_ITEM='gca-faceplate-game-artwork';
export function steamAppId(value:unknown):number|null{
  const id=typeof value==='number'?value:typeof value==='string'&&/^\d+$/.test(value)?Number(value):NaN;
  return Number.isSafeInteger(id)&&id>0&&id<=0xffffffff?id:null;
}
export function artworkGamePath(appid:number){
  const id=steamAppId(appid);if(id===null)throw new Error('Invalid Steam game');
  return `${GAME_ARTWORK_ROUTE}/${id}`;
}
export function menuItemLabel(language:unknown){return language==='fr'?'Illustration JSAUX Faceplate…':'JSAUX Faceplate artwork…';}
function source(value:unknown){try{return typeof value==='function'?Function.prototype.toString.call(value):'';}catch{return '';}}
function walk(value:any,visit:(item:any)=>void){
  const queue=[value],seen=new Set<any>();let budget=400;
  while(queue.length&&budget-->0){const item=queue.shift();if(!item||typeof item!=='object'||seen.has(item))continue;seen.add(item);visit(item);
    if(Array.isArray(item))queue.push(...item.slice(0,80));else{if(item.props)queue.push(item.props);if(item.children)queue.push(item.children);}}
}
export function menuAppId(items:unknown,hint?:unknown):number|null{
  const ids=new Set<number>();walk(items,item=>{for(const value of [item.app?.appid,item.overview?.appid]){const id=steamAppId(value);if(id!==null)ids.add(id);}});
  if(ids.size===1)return [...ids][0];if(ids.size>1)return null;
  return steamAppId(hint);
}
export function addGameArtworkItem<T>(items:T[],hint:unknown,create:(appid:number)=>T):T[]{
  let properties=-1,launch=false;items.forEach((item:any,index)=>{if(Array.isArray(item))return;if(item?.key==='properties')properties=index;
    walk(item,node=>{const code=source(node.onSelected);if(code.includes('AppProperties'))properties=index;if(code.includes('launchSource'))launch=true;});});
  const appid=menuAppId(items,hint);
  // Recognize only an actual game menu. Screenshot/media menus stay untouched.
  if(properties<0||appid===null||!launch)return items;
  const copy=items.filter((item:any)=>item?.key!==GAME_ARTWORK_ITEM);
  const target=items[properties];const at=copy.indexOf(target);
  copy.splice(at<0?copy.length:at,0,create(appid));return copy;
}

declare const appStore:any;
export function steamGameTitle(appid:number,fallback=''){
  try{const name=typeof appStore==='undefined'?'':appStore?.GetAppOverviewByAppID?.(appid)?.display_name;
    return typeof name==='string'&&name.trim()?name.trim().slice(0,200):fallback;
  }catch{return fallback;}
}
