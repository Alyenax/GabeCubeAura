/** Product previews only; native PanelSection/Field supply all control spacing and paint. */
export const COMPACT_QUICK_CSS=`
#gca-compact-root{min-width:0}
#gca-compact-root .gca-compact-game-art{display:block;width:100%;aspect-ratio:460/215;object-fit:cover}
#gca-compact-root .gca-compact-game-title{display:block;font-size:12px;line-height:16px;margin-top:8px;overflow-wrap:anywhere}
#gca-compact-root .gca-compact-art-link{width:100%;min-width:0;padding:0}
#gca-compact-root .gca-compact-art-empty{min-height:100px;display:flex;align-items:center;justify-content:center}
#gca-compact-root .gca-compact-led-caption{display:flex;justify-content:space-between;gap:8px;font-size:12px;line-height:16px;margin-top:8px;color:var(--gpSystemLighterGrey,#b8bcbf)}
#gca-compact-root .gca-compact-led{display:grid;grid-template-columns:repeat(17,minmax(0,1fr));gap:2px;background:#000;padding:4px;margin-top:4px}
#gca-compact-root .gca-compact-led i{height:10px;min-width:0}
#gca-compact-root .gca-compact-clock{font-variant-numeric:tabular-nums}
#gca-compact-root small{display:block;font-size:12px;line-height:16px;color:var(--gpSystemLighterGrey,#b8bcbf);margin-top:4px}
#gca-compact-root .gca-compact-error small,#gca-compact-root .gca-compact-action-error{color:#ffc7b5}
#gca-compact-root .gca-compact-timer-actions{display:flex;gap:8px;margin:8px 0}
#gca-compact-root .gca-compact-timer-actions>*{flex:1;min-width:0}
#gca-compact-root .gca-compact-artwork-guidance{color:#ffd27a;margin-top:8px;line-height:1.4}
#gca-compact-root .gca-compact-artwork-guidance small{color:#ffd27a}
#gca-compact-root .gca-compact-artwork-guidance button{margin-top:8px}
#gca-compact-root .gca-compact-wide{width:100%;min-width:0}
#gca-compact-root .gca-compact-editor p{font-size:12px;line-height:16px;color:var(--gpSystemLighterGrey,#b8bcbf)}
`;
