import { cloneElement, Fragment, isValidElement, useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import { getUILanguage, subscribeUILanguage, translate, translateUIProperties, type TextProperties, type UILanguage } from "./i18n";

export function Localized({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore(subscribeUILanguage, getUILanguage, getUILanguage);
  return <>{translateNode(children, locale)}</>;
}

export function translateNode(value: unknown, locale: UILanguage): ReactNode {
  if (typeof value === "string") return translate(value, locale);
  if (Array.isArray(value)) return value.map((node) => translateNode(node, locale));
  if (!isValidElement(value)) return value as ReactNode;
  const element = value as ReactElement<TextProperties>;
  // Custom components manage their own props; never execute them as functions.
  // React keys, refs, events and native Decky focus identities are retained.
  if (element.props.translate === "no" || element.props.translate === false
      || (typeof element.type !== "string" && element.type !== Fragment)) return element;
  const props = translateUIProperties(element.props, locale, (node) => translateNode(node, locale));
  return Array.isArray(props.children)
    ? cloneElement(element, props, ...props.children)
    : cloneElement(element, props);
}

