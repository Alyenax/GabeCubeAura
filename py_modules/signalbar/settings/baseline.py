"""Complete saved choices for later calibration; never a public-default import."""
from copy import deepcopy

from .store import DEFAULTS

BASELINE_SCHEMA = 'gabecubeaura-configuration-baseline-v1'
SOURCES = ('settings', 'faceplate_preferences', 'ambience_profiles', 'artwork_library', 'support')


def reject_credentials(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).lower() in {'api_key','access_token','refresh_token','client_secret','password','authorization'}:
                raise ValueError('Authentication secrets cannot enter a configuration reference')
            reject_credentials(item)
    elif isinstance(value,list):
        for item in value:reject_credentials(item)


def settings_baseline(values):
    missing = sorted(set(DEFAULTS)-set(values))
    if missing:
        raise ValueError('Configuration snapshot is missing saved settings: '+', '.join(missing))
    # Only supported persisted settings, never arbitrary runtime/provider fields.
    saved = {key:deepcopy(values[key]) for key in DEFAULTS}
    return dict(schema=BASELINE_SCHEMA, purpose='future-public-calibration-reference',
                applied_as_defaults=False, settings=saved,
                coverage=dict(settings_keys=sorted(saved), settings_count=len(saved),
                              missing_settings=[], sources_included=['settings'],
                              sources_not_collected=list(SOURCES[1:])),
                exclusions=['API keys', 'GitHub authorization tokens', 'media bytes',
                            'runtime state, running timers and connected-device telemetry'])


def collect_sources(engine, diagnostics):
    """Read each independent store through its own lock; perform no activation."""
    with engine.ambience.lock:
        ambiences=deepcopy(engine.ambience.items)
    return dict(faceplate_preferences=engine.faceplate_preferences.read().as_dict(),
                ambience_profiles=ambiences,
                artwork_library=engine.faceplate.steamgriddb.configuration_snapshot(),
                support=dict(automatic_diagnostic_upload=bool(diagnostics.status()['automatic_upload'])))


def add_sources(baseline, sources):
    if set(sources) != set(SOURCES)-{'settings'}:
        raise ValueError('Configuration snapshot is missing an independent settings store')
    baseline.update(deepcopy(sources))
    baseline['coverage'].update(sources_included=list(SOURCES), sources_not_collected=[])
    return baseline


def validate_complete_baseline(payload):
    reject_credentials(payload)
    baseline=payload.get('calibration_reference') if isinstance(payload,dict) else None
    if (not isinstance(baseline,dict) or baseline.get('schema')!=BASELINE_SCHEMA
            or not isinstance(baseline.get('settings'),dict)
            or set(baseline['settings']) != set(DEFAULTS)
            or any(not isinstance(baseline.get(key),dict) for key in SOURCES[1:])
            or baseline.get('applied_as_defaults') is not False):
        raise ValueError('The saved configuration reference is incomplete')
    expected=settings_baseline(baseline['settings'])['coverage']
    coverage=baseline.get('coverage',{})
    if (coverage.get('settings_keys')!=expected['settings_keys']
            or coverage.get('settings_count')!=len(DEFAULTS)
            or coverage.get('missing_settings')!=[]
            or coverage.get('sources_included')!=list(SOURCES)
            or coverage.get('sources_not_collected')!=[]):
        raise ValueError('The saved configuration coverage is incomplete')
    return baseline
