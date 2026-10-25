# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Compact City count and one visible fact in the native 64 x 9 rail."""
from .scenes import Canvas, draw_text, measure_text
from .bottom_stats import CLOCK, SESSION_CLOCK, TROPHY, _duration, _counts, _icon as draw_stats_icon
from .artwork_dashboard import WARM_WHITE, PLAYER_ONE, PLAYER_TWO, _battery_bar
from .playtime import COLOURS

BACKGROUND = (8, 12, 20)
WHITE = WARM_WHITE
ACCENT = (255, 210, 72)  # Existing City population marker.
SMILE = ('0011100','0111110','1101011','1111111','1011101','0100010','0011100')


def compact_players(players):
    from .player_city import population_tier
    population_tier(players)
    if players < 1000:
        return str(players)
    if players < 100000:
        tenths = players // 100
        return str(tenths // 10) + ('.' + str(tenths % 10) if tenths % 10 else '') + 'k'
    return str(players // 1000) + 'k'


def row_label(row, available):
    """Select only the visible fact. No hidden statistics enter the image."""
    countdown = row.get('countdown') or {}
    if countdown.get('state') == 'ended':
        label=next(label for label in ("TIME'S UP","TIME'SUP","UP") if measure_text(label)<=available)
        return None, label, COLOURS['urgent']
    if countdown.get('state') == 'remaining':
        minutes = max(1, min(9999, int(countdown.get('minutes', 1))))
        label = '<1MIN' if countdown.get('last_minute') else (str(minutes)+'MIN' if minutes < 60
                else f'{minutes//60}H{minutes%60:02d}')
        if measure_text(label)>available:
            label=f'{minutes//60}H'
        return None, label, COLOURS.get(countdown.get('urgency'), COLOURS['normal'])
    mode = row.get('mode', 'controllers')
    if mode == 'session':
        label=_duration(row.get('session_minutes'))
        if measure_text(label)+7>available:
            minutes=row.get('session_minutes')
            hours=minutes//60 if type(minutes) is int and minutes>=0 else None
            label='--H' if hours is None else '>9KH' if hours>9999 else f'{hours}H'
            if measure_text(label)+7>available:label=f'{hours//1000}KH'
        return SESSION_CLOCK, label, WARM_WHITE
    if mode == 'total':
        minutes = row.get('total_minutes')
        hours = minutes//60 if type(minutes) is int and minutes >= 0 else None
        label = '--H' if hours is None else f'{hours}H' if hours <= 9999 else '>9999H'
        if measure_text(label)+7>available:
            label='>9KH' if hours>9999 else f'{hours//1000}KH'
        return CLOCK, label, WARM_WHITE
    if mode == 'achievements':
        counts = _counts(row)
        label = f'{counts[0]}/{counts[1]}' if counts else '--/--'
        if measure_text(label) + 7 > available:
            label = f'{counts[0]*100//counts[1]}%' if counts else '--%'
        return TROPHY, label, WARM_WHITE
    percent = row.get('percent')
    label = '--%' if type(percent) is not int else f'{max(0,min(100,percent))}%'
    return None, label, PLAYER_ONE


def _icon(canvas, x, pattern, colour, y=48):
    for dy, line in enumerate(pattern):
        for dx, bit in enumerate(line):
            if bit not in ('.', '0'):
                canvas.pixel(x+dx, y+dy, colour)


def build_rail(players, row=None):
    """Reuse Dashboard labels, battery drawing and coloured statistics icons."""
    row = row if isinstance(row, dict) else {}
    if row.get('mode') == 'dashboard':
        from .artwork_dashboard import _draw_bottom_row
        canvas = Canvas(BACKGROUND)
        facts = dict(row.get('dashboard') or {})
        mode = facts.pop('bottom_mode', 'controllers')
        _draw_bottom_row(canvas, mode, countdown=row.get('countdown'), **facts)
        return canvas.bytes()[45*64*3:]
    label = compact_players(players)
    count_width = measure_text(label)
    mode = row.get('mode', 'count')
    count_only = mode == 'count' and not row.get('countdown')
    if count_only:
        from .player_city import rail_layout
        label,count_width=rail_layout(players)
        canvas = Canvas(BACKGROUND)
        left = (64-count_width-9)//2
        _icon(canvas, left, SMILE, ACCENT, 46)
        _draw_count(canvas, left+9, label)
        return canvas.bytes()[45*64*3:]
    left_width=count_width+9
    available=64-left_width-2
    icon, value, accent = row_label(row, available)
    controller = mode == 'controllers' and not row.get('countdown')
    right_width = measure_text(value) + (7 if icon else 0)
    if controller:
        value_width=13 if row.get('battery_style') == 'bar' else measure_text(value)
        prefix=min(10,max(7,available-value_width))
        right_width = prefix+value_width
    margin = min(2, max(0, (64-left_width-right_width-2)//2))
    if left_width+right_width+2 > 64:
        raise ValueError('City information row exceeds 64 columns')
    canvas = Canvas(BACKGROUND)
    _icon(canvas,margin,SMILE,ACCENT,46)
    _draw_count(canvas, margin+9, label)
    right = 64-margin-right_width
    if controller:
        draw_text(canvas, right, 48, 'P1', PLAYER_ONE)
        if row.get('battery_style') == 'bar':
            _battery_bar(canvas, right+prefix, 48, row, PLAYER_ONE, True)
        else:
            draw_text(canvas, right+prefix, 48, value, PLAYER_ONE)
    else:
        if icon:
            draw_stats_icon(canvas, right, icon)
            right += 7
        draw_text(canvas, right, 48, value, accent)
    return canvas.bytes()[45*64*3:]


def _draw_count(canvas, x, label):
    for character in label:
        if character == ',':
            from .player_city import DIGITS
            _icon(canvas, x, DIGITS[','], WHITE)
            x += len(DIGITS[','][0])+1
            continue
        if character == 'k':
            _icon(canvas, x, ('100','100','101','110','101'), WHITE)
        else:
            draw_text(canvas, x, 48, character, WHITE)
        x += measure_text(character)+1


def fit_rail_palette(art, rail):
    """Keep City pixels exact; fit only rail colours if its global GIF is full.

    A single palette for the complete cycle keeps the static rail from changing
    colour between frames. Most banks have room for every Dashboard colour.
    """
    from collections import Counter
    from .artwork_dashboard import DURATION_HAND, WEATHER_WHITE, SEPARATOR_GREY
    colours = {frame[n:n+3] for frame in art for n in range(0,len(frame),3)}
    counts = Counter(rail[n:n+3] for n in range(0,len(rail),3))
    missing = set(counts)-colours
    budget = 256-len(colours)
    if len(missing) <= budget:
        return rail
    # Preserve native labels/icons before background and secondary accents.
    background = max(counts, key=counts.get)
    priority = [bytes(COLOURS['urgent']), bytes(WARM_WHITE), bytes(PLAYER_ONE),
                bytes(DURATION_HAND), bytes(PLAYER_TWO), bytes(WEATHER_WHITE),
                bytes(SEPARATOR_GREY), bytes(ACCENT), background]
    selected = []
    for colour in priority + sorted(missing, key=lambda colour:(-counts[colour],colour)):
        if colour in missing and colour not in selected and len(selected) < budget:
            selected.append(colour)
    allowed = sorted(colours | set(selected))
    mapping = {}
    for colour in counts:
        mapping[colour] = colour if colour in allowed else min(allowed,
            key=lambda target:sum((a-b)**2 for a,b in zip(colour,target)))
    return b''.join(mapping[rail[n:n+3]] for n in range(0,len(rail),3))
