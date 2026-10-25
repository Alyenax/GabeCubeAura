import { useState } from "react";
import { ButtonItem, PanelSection, PanelSectionRow, ToggleField } from "../localized_ui";
import type { Status } from "../types";
import {FaceplateDiagnostics} from './FaceplateDiagnostics';

export const FLASH_ADVISORY = "One animated GIF counts as one transfer. Counters record USB acknowledgements, not memory wear or visible playback.";

export function FlashProtectionPanel({ status, onChange, collapsible = false }: {
  status: Status; onChange?: (enabled: boolean) => Promise<void>; collapsible?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const flash = status.faceplate.flash_protection;
  const t=(en:string,fr:string)=>status.ui_language==='fr'?fr:en;
  const refreshHelp = t("On: battery percentages in 5% steps (77% → 75%) and Dashboard clock updates in 5-minute steps (14:03 → 14:00). Off: exact percentages and one-minute updates.","Activée : batteries par paliers de 5 % (77 % → 75 %) et heure des Dashboard par paliers de 5 minutes (14:03 → 14:00). Désactivée : pourcentages exacts et actualisation chaque minute.");
  const protectionLabel = flash?.enabled === false ? t("Economy refresh off","Actualisation économe désactivée")
    : t("Economy refresh on","Actualisation économe activée");
  return <PanelSection title={t("Faceplate refresh and statistics","Actualisation et statistiques de la faceplate")}>
    {collapsible ? <PanelSectionRow><ButtonItem
      label="Transfer status and statistics" description={protectionLabel}
      onClick={() => setExpanded(value => !value)}
    >{expanded ? "Hide details" : "Show details"}</ButtonItem></PanelSectionRow> : null}
    {!collapsible || expanded ? <>
    {onChange ? <PanelSectionRow><ToggleField
      label={t("Economy refresh","Actualisation économe")}
      checked={flash?.enabled ?? true} onChange={onChange}
    /></PanelSectionRow> : null}
    <PanelSectionRow><div style={{fontSize:'.8em',lineHeight:1.45}}>{refreshHelp}</div></PanelSectionRow>
    <PanelSectionRow><div style={{ fontSize: ".8em", lineHeight: 1.5, width: "100%" }}>
      {flash ? <>
        <div>{t('Confirmed GIF transfers: ','Transferts GIF confirmés : ')}{flash.session.confirmed}{t(' this session · ',' cette session · ')}{flash.total.confirmed}{t(' total',' au total')}</div>
        <div>{t('Avoided: ','Évités : ')}{flash.total.reused} · {t('Delayed: ','Différés : ')}{flash.total.deferred} · {t('Unconfirmed: ','Non confirmés : ')}{flash.total.uncertain}</div>
      </> : null}
      <FaceplateDiagnostics status={status} summaryShown/>
    </div></PanelSectionRow>
    </> : null}
  </PanelSection>;
}
