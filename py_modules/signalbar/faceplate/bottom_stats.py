# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Native 64×9 in-game statistics. Never scale text or rotate hidden pages."""
from .scenes import draw_text, measure_text

CLOCK = ('.CCC.', 'C.Y.C', 'C.Y.C', 'C..YC', '.CCC.')
SESSION_CLOCK = tuple(row.translate(str.maketrans('CY', 'YC')) for row in CLOCK)
TROPHY = ('AAAAA', 'AAAAA', '.AAA.', '..A..', '.AAA.')


def _icon(canvas, x, pattern):
    from .artwork_dashboard import PLAYER_ONE, PLAYER_TWO, DURATION_HAND
    colours = {'C': PLAYER_ONE, 'A': PLAYER_TWO, 'Y': DURATION_HAND}
    for y, row in enumerate(pattern, 48):
        for dx, symbol in enumerate(row):
            if symbol in colours:
                canvas.pixel(x + dx, y, colours[symbol])


def _duration(minutes):
    if type(minutes) is not int or minutes < 0:
        return '--H--'
    hours, minute = divmod(minutes, 60)
    return f'{hours}H{minute:02d}' if hours < 100 else f'{hours}H' if hours <= 9999 else '>9999H'


def _counts(stats):
    done, total = stats.get('achieved'), stats.get('achievements_total')
    if type(done) is int and type(total) is int and 0 <= done <= total and total > 0:
        return done, total
    return None


def draw_stats_row(canvas, variant, *, session_minutes=None, game_stats=None,
                   controllers=(), battery_style='percent', show_p2=False,
                   connected_controller_count=None, **_):
    """Draw one statistics row, returning False for unknown variants."""
    from .artwork_dashboard import (PLAYER_ONE, PLAYER_TWO, WARM_WHITE,
                                   PROGRESS_EMPTY, _battery_bar)
    stats = game_stats if isinstance(game_stats, dict) else {}
    items = list(controllers or ())
    counts = _counts(stats)
    duration = _duration(session_minutes)
    if variant in ('a', 'e'):
        minutes = stats.get('total_minutes') if variant == 'e' else session_minutes
        if variant == 'e':
            hours = minutes // 60 if type(minutes) is int and minutes >= 0 else None
            duration = '--H' if hours is None else f'{hours}H' if hours < 100000 else f'{hours // 1000}KH'
        raw = items[0].get('percent') if items else None
        displayed = min(99, raw) if variant == 'a' and raw is not None else raw
        battery_label = '--%' if displayed is None else f'{displayed}%'
        # Reserve a stable two-digit percentage slot; only a real 100% in
        # the total row needs its four-column expansion to the left.
        battery_width = 13 if battery_style == 'bar' else 15 if displayed == 100 else 11
        battery_x = 63 - battery_width
        duration_x = 1 if variant == 'a' else 8
        label = f'{counts[0]}/{counts[1]}' if counts else '--/--'
        count_offset = 7

        def available_gap():
            return battery_x - (duration_x + measure_text(duration)) - (count_offset + measure_text(label))

        if available_gap() < 4:
            label = f'{counts[0]*100//counts[1]}%' if counts else '--%'
        if available_gap() < 4:
            hours = minutes//60 if type(minutes) is int and minutes >= 0 else None
            duration = '--H' if hours is None else (f'{hours}H' if hours < 1000
                else f'{hours//1000}KH' if hours < 100000 else '>9KH')
        if available_gap() < 4:
            count_offset = 6  # One dark column inside the trophy/value block.
        # Spread the free columns on both sides of the achievement block.
        trophy_x = duration_x + measure_text(duration) + max(2,available_gap()//2)
        count_x = trophy_x + count_offset
        if variant == 'e':
            _icon(canvas, 1, CLOCK)
        draw_text(canvas, duration_x, 48, duration, WARM_WHITE)
        _icon(canvas, trophy_x, TROPHY); draw_text(canvas, count_x, 48, label, WARM_WHITE)
        if battery_style == 'bar':
            _battery_bar(canvas, battery_x, 48, items[0] if items else {}, PLAYER_ONE, True)
        else:
            draw_text(canvas, 63 - measure_text(battery_label), 48, battery_label, PLAYER_ONE)
        return True
    if variant == 'c':
        if measure_text(duration) > 27:
            duration = '--H--'
        _icon(canvas, 1, SESSION_CLOCK); draw_text(canvas, 8, 48, duration, WARM_WHITE)
        draw_text(canvas, 39, 48, 'P1', PLAYER_ONE)
        raw = items[0].get('percent') if items else None
        if battery_style == 'bar':
            _battery_bar(canvas, 49, 48, items[0] if items else {}, PLAYER_ONE, True)
        else:
            label = '--%' if raw is None else f'{raw}%'
            draw_text(canvas, min(51, 64 - measure_text(label)), 48, label, PLAYER_ONE)
        return True
    if variant == 'b':
        minutes = stats.get('total_minutes')
        hours = minutes // 60 if type(minutes) is int and minutes >= 0 else None
        label = '--H' if hours is None else f'{hours}H' if hours < 100000 else f'{hours // 1000}KH'
        ratio = f'{counts[0]}/{counts[1]}' if counts else '--/--'
        # Large counters use the exact achieved count; total stays available
        # in the saved snapshot, never approximated as a fake ratio.
        if 8 + measure_text(label) + 3 + 5 + 2 + measure_text(ratio) > 64:
            ratio = str(counts[0]) if counts else '--'
        if 8 + measure_text(label) + 3 + 5 + 2 + measure_text(ratio) > 64:
            label = '--H'
        _icon(canvas, 1, CLOCK); draw_text(canvas, 8, 48, label, WARM_WHITE)
        x = max(8 + measure_text(label) + 3, 62 - measure_text(ratio) - 7)
        _icon(canvas, x, TROPHY); draw_text(canvas, x + 7, 48, ratio, WARM_WHITE)
        return True
    if variant == 'd':
        _icon(canvas, 2, TROPHY)
        percent = counts[0] * 100 // counts[1] if counts else None
        label = '--%' if percent is None else f'{percent}%'
        draw_text(canvas, 9, 48, label, WARM_WHITE)
        left = max(25, 9 + measure_text(label) + 3)
        width = 62 - left
        canvas.rect(left, 49, width, 3, PROGRESS_EMPTY)
        filled = round(width * percent / 100) if percent is not None else 0
        if filled:
            canvas.rect(left, 49, filled, 3, PLAYER_TWO)
        return True
    return False
