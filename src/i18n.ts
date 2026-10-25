import { french } from "./i18n/fr";

export type UILanguage = "en" | "fr";
let language: UILanguage = "en";
const listeners = new Set<() => void>();
const lowerCaseCopy = new Map(Object.entries(french).map(([key, value]) => [key.toLowerCase(), value]));
const englishCopy=new Map(Object.entries(french).filter(([source,target])=>source!==target).map(([source,target])=>[target,source]));

export function getUILanguage(): UILanguage { return language; }
export function setUILanguage(value: unknown): void {
  const next = value === "fr" ? "fr" : "en";
  if (next === language) return;
  language = next;
  listeners.forEach((listener) => listener());
}
export function subscribeUILanguage(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

// English is the source catalogue and the fallback for technical diagnostics.
// Only UI text is passed here: never settings keys, paths, tokens or game IDs.
export function translate(text: string, locale: UILanguage = language): string {
  if(!text.trim())return text;
  if(locale==='en'){
    const exact=englishCopy.get(text.trim());
    if(exact!==undefined)return(text.match(/^\s*/)?.[0]??'')+exact+(text.match(/\s*$/)?.[0]??'');
    for(const pattern of englishPatterns){
      const match=pattern.regex.exec(text);if(!match)continue;
      const values=new Map(pattern.parameters.map((p,i)=>[p.index,p.localized?translate(match[i+1]??'','en'):match[i+1]??'']));
      return pattern.translation.replace(/\{(\d+)\}/g,(_token,index:string)=>values.get(index)??'');
    }
    return text;
  }
  const exact = french[text] ?? french[text.trim()] ?? lowerCaseCopy.get(text.trim().toLowerCase());
  if (exact !== undefined) {
    return text.match(/^\s*/)?.[0] + exact + (text.match(/\s*$/)?.[0] ?? "");
  }
  for (const pattern of patterns) {
    const match = pattern.regex.exec(text);
    if (match) return pattern.translation.replace(/\{(\d+)(:t)?\}/g,
      (_token, index: string, localized: string | undefined) => {
        const value = match[Number(index) + 1] ?? "";
        return localized ? translate(value, locale) : value;
      });
  }
  return text;
}

// Placeholders retain names, paths, numbers and server details verbatim.
// Anchored patterns do not rewrite arbitrary substrings in user content.
const patterns = Object.entries(french).filter(([source]) => /\{\d+\}/.test(source))
  .sort(([a], [b]) => b.replace(/\{\d+\}/g,'').length-a.replace(/\{\d+\}/g,'').length)
  .map(([source, translation]) => ({
    regex: new RegExp("^" + source.split(/\{\d+\}/).map((part) =>
      part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("([\\s\\S]*?)") + "$"),
    translation,
  }));
const englishPatterns=Object.entries(french).filter(([source])=>/\{\d+\}/.test(source))
  .sort((a,b)=>b[1].length-a[1].length).map(([source,target])=>({
    regex:new RegExp('^'+target.split(/\{\d+(?::t)?\}/).map(p=>p.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('([\\s\\S]*?)')+'$'),
    parameters:[...target.matchAll(/\{(\d+)(:t)?\}/g)].map(m=>({index:m[1],localized:!!m[2]})),translation:source,
  }));

export type TextProperties = Record<string, unknown>;
const textProperties = ["label", "title", "description", "tooltip", "placeholder", "alt", "aria-label", "menuLabel", "strDefaultLabel", "strTitle", "strDescription", "strOKButtonText", "strCancelButtonText"];

export function translateUIProperties<T extends TextProperties>(
  source: T, locale: UILanguage, translateNode: (value: unknown) => unknown,
): T {
  const result: TextProperties = { ...source };
  const ignored = source.untranslatedProps as readonly string[] | undefined;
  for (const key of [...textProperties, "children"]) {
    if (key in source && !ignored?.includes(key)) result[key] = translateNode(source[key]);
  }
  for (const key of ["rgOptions", "pages"]) {
    if (!Array.isArray(source[key]) || (key === "rgOptions" && source.untranslatedOptions)) continue;
    result[key] = (source[key] as unknown[]).map((entry) => {
      if (!entry || typeof entry !== "object") return entry;
      const option = entry as TextProperties;
      // data, route and content are deliberately left intact.
      return { ...option, ...(typeof option.label === "string" ? { label: translate(option.label, locale) } : {}),
        ...(typeof option.title === "string" ? { title: translate(option.title, locale) } : {}) };
    });
  }
  delete result.untranslatedProps;
  delete result.untranslatedOptions;
  return result as T;
}
