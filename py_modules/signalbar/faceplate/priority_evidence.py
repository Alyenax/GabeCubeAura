# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Fixed-label diagnostic vocabulary, independent from admission/USB policy."""
BLOCKERS=('plugin-disabled','faceplate-disabled','onboarding-recovery','onboarding-applying',
    'mode-disabled','panel-route-off','faceplate-suspended','power-target-off','panel-powered-off',
    'engine-stopping','thermal-protection','steam-explicit-lease','steam-effective-priority',
    'countdown-last-5-min','external-matrix-hold','light-event-active',
    'launch-artwork-active','launch-artwork-pending')

def clean(value):
    value=value if isinstance(value,dict) else {}
    first=value.get('first_blocker')
    out=dict(first_blocker=first if first in (*BLOCKERS,'none') else 'unclassified',evaluated={},steam_inputs={})
    age=value.get('steam_inputs_age_ms')
    out['steam_inputs_age_ms']=age if type(age) is int and 0<=age<=2147483647 else None
    if isinstance(value.get('evaluated'),dict):
        out['evaluated']={k:v for k,v in value['evaluated'].items() if k in BLOCKERS and type(v) is bool}
    inputs=value.get('steam_inputs')
    if isinstance(inputs,dict):
        out['steam_inputs']={k:inputs[k] for k in ('download_lease','native_effect','guard_hard_priority') if type(inputs.get(k)) is bool}
        if inputs.get('policy') in ('cooperative','downloads','critical'):out['steam_inputs']['policy']=inputs['policy']
        if inputs.get('guard_reason') in ('startup-settle','repeated-led-activity','external-led-change','other'):
            out['steam_inputs']['guard_reason']=inputs['guard_reason']
    event=value.get('light_event')
    if isinstance(event,dict) and event.get('kind') in ('notification','achievement','screenshot','record-start','record-stop'):
        out['light_event']=dict(kind=event['kind'])
    if value.get('countdown_source') in ('preview','parental','free','none'):out['countdown_source']=value['countdown_source']
    return out
