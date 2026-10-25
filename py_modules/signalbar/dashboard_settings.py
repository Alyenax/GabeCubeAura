"""Independent Dashboard information choices, with legacy display preservation."""

CHOICES = {'bottom_mode': {'next_hour', 'today', 'controllers'},
           'battery_style': {'percent', 'bar'},
           'game_row': {'existing', 'a', 'b', 'c', 'd', 'e'},
           'weather_position': {'left', 'center', 'right'}}
FLAGS = {'show_weather', 'show_bottom_row', 'show_p2', 'show_session'}


def validate_contexts(raw):
    if not isinstance(raw, dict):
        return {}
    result = {}
    for context in ('home', 'game'):
        value = raw.get(context)
        if not isinstance(value, dict):
            continue
        result[context] = {key: item for key, item in value.items()
                           if key in FLAGS and type(item) is bool
                           or key in CHOICES and isinstance(item, str) and item in CHOICES[key]}
        if context == 'home':
            result[context].pop('game_row', None)
    return result


def dashboard_context(values, game_running=False):
    """Missing context fields retain the old Home/game behaviour exactly."""
    session = bool(game_running and values.get('faceplate_dashboard_game_session', True))
    resolved = {
        'show_weather': bool(values.get('faceplate_dashboard_show_weather', True)),
        'show_bottom_row': bool(values.get('faceplate_dashboard_show_bottom_row', True)),
        'bottom_mode': 'controllers' if session else values.get('faceplate_dashboard_bottom_mode', 'next_hour'),
        'battery_style': values.get('faceplate_dashboard_battery_style', 'percent'),
        'show_p2': bool(values.get('faceplate_dashboard_show_p2', False)),
        'show_session': session,
        'game_row': 'existing',
        'weather_position': 'right',
    }
    contexts = validate_contexts(values.get('faceplate_dashboard_contexts'))
    resolved.update(contexts.get('game' if game_running else 'home', {}))
    if not game_running:
        resolved['show_session'] = False
    return resolved
