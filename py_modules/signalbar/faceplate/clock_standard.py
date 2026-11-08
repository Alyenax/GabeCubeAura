# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax. Monogram glyph data retains CC0; see THIRD_PARTY_NOTICES.md.
"""Approved native clock/date compositions and finite, minute-aligned packets.

Pure rendering, no serial/network I/O or optional font dependencies. The nine
compositions follow the approved prototypes; the retired Escalier is absent.
"""
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import unicodedata

ASSETS = Path(__file__).resolve().parents[3] / 'assets/clocks'
PALETTES = ('amber', 'glacier', 'rose', 'sage', 'lavender', 'ivory')
DESIGNS = ('meridian', 'halo', 'almanac', 'quadrant', 'cardinal',
           'horizon', 'column', 'week', 'date-card')
TINY = dict(zip('0123456789APM', (
    ('111','101','101','101','111'), ('010','110','010','010','111'),
    ('110','001','010','100','111'), ('110','001','010','001','110'),
    ('101','101','111','001','001'), ('111','100','110','001','110'),
    ('011','100','111','101','111'), ('111','001','010','010','010'),
    ('111','101','111','101','111'), ('111','101','111','001','110'),
    ('010','101','111','101','101'), ('110','101','110','100','100'),
    ('101','111','111','101','101'))))
DAYS = {'fr': ('DIM','LUN','MAR','MER','JEU','VEN','SAM'),
        'en': ('SUN','MON','TUE','WED','THU','FRI','SAT')}
MONTHS = {'fr': ('JANV','FÉV','MARS','AVR','MAI','JUIN','JUIL','AOÛT','SEPT','OCT','NOV','DÉC'),
          'en': ('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC')}


def normalize_options(options=None):
    if options is None: options = {}
    if not isinstance(options, dict): raise ValueError('Invalid clock options')
    result = {'palette': options.get('palette', 'amber'),
              'format': options.get('format', '24'),
              'language': options.get('language', 'en')}
    if (not isinstance(result['palette'], str) or result['palette'] not in PALETTES
            or result['format'] not in ('24', '12') or result['language'] not in ('fr', 'en')):
        raise ValueError('Choose supported clock colours, format and language')
    return result


@lru_cache(maxsize=1)
def _data():
    return (json.loads((ASSETS/'geometry.json').read_text()),
            json.loads((ASSETS/'monogram.json').read_text()))


def _round(value):
    # Match the approved integer raster, including JavaScript's half-up rule.
    return math.floor(value + .5)


def render_indices(design, at, options=None):
    if design not in DESIGNS: raise ValueError('Choose an available standard clock')
    options = normalize_options(options)
    geometry, atlas = _data()
    language, twelve = options['language'], options['format'] == '12'
    hour, minute = at.hour, at.minute
    hours, minutes = f'{hour % 12 or 12:02}' if twelve else f'{hour:02}', f'{minute:02}'
    day, month_number = f'{at.day:02}', f'{at.month:02}'
    weekday = DAYS[language][(at.weekday()+1) % 7]
    month = MONTHS[language][at.month-1]
    ampm = 'PM' if hour >= 12 else 'AM'
    pixels = bytearray(64*54)

    def dot(x, y, colour):
        x, y = _round(x), _round(y)
        if not 0 <= x < 64 or not 0 <= y < 54: raise ValueError('Clock pixel outside matrix')
        pixels[y*64+x] = colour

    def line(x0, y0, x1, y1, colour):
        x0,y0,x1,y1 = map(_round, (x0,y0,x1,y1))
        dx,sx,dy,sy = abs(x1-x0),1 if x0<x1 else -1,-abs(y1-y0),1 if y0<y1 else -1
        error = dx+dy
        while True:
            dot(x0,y0,colour)
            if x0==x1 and y0==y1: break
            twice=2*error
            if twice>=dy: error+=dy; x0+=sx
            if twice<=dx: error+=dx; y0+=sy

    def mono_width(label, font='small'):
        return sum(atlas[font]['glyphs'][c]['advance'] for c in label)-1

    def mono(label,x,y,colour,font='small'):
        x=_round(x)
        for char in label:
            glyph=atlas[font]['glyphs'][char]
            for j,row in enumerate(glyph['rows']):
                for i,on in enumerate(row):
                    if on=='1': dot(x+glyph['dx']+i,y+glyph['dy']+j,colour)
            x+=glyph['advance']

    def centre_mono(label,cx,y,colour,font='small'):
        mono(label,_round(cx-(mono_width(label,font)-1)/2),y,colour,font)

    def tiny(label,x,y,colour):
        for char in label:
            for j,row in enumerate(TINY[char]):
                for i,on in enumerate(row):
                    if on=='1': dot(x+i,y+j,colour)
            x+=4

    def time(cx,y): centre_mono(hours+':'+minutes,cx,y,2,'monogram')

    def analog_text(label,cx,y,colour,scale=1,big=False):
        font=geometry['big_digits' if big else 'font']
        base=lambda c: unicodedata.normalize('NFD',c)[0]
        width=sum((len(font[base(c)][0])+1)*scale for c in label)-scale
        x=_round(cx-(width-1)/2)
        for char in label:
            bare=base(char)
            if char!=bare:
                dot(x+scale,y-2*scale,colour)
                if char=='Û': dot(x+2*scale,y-scale,colour)
            glyph=font[bare]
            for j,row in enumerate(glyph):
                for i,on in enumerate(row):
                    if on=='1':
                        for yy in range(scale):
                            for xx in range(scale): dot(x+i*scale+xx,y+j*scale+yy,colour)
            x+=(len(glyph[0])+1)*scale

    def ticks(cx,cy,r,ring=False):
        # Integer geometry was baked from the approved raster. Half-pixel trig
        # ties otherwise vary between host math libraries and shift a marker.
        for coordinates in geometry['ticks'][f'{cx},{cy},{r}']: line(*coordinates)
        if ring:
            for i,coordinates in enumerate(geometry['halo_ring']):
                if i%5: dot(*coordinates,1)

    def hands(cx,cy,h_len,m_len):
        hx,hy,mx,my=geometry['hands'][f'{cx},{cy},{h_len},{m_len}'][(hour%12)*60+minute]
        hp,mp=(hx,hy),(mx,my)
        # Both hands share the exact integer pivot and one-pixel centrelines.
        # A second x+1 stroke shifts the hour hand's visible axis by half a pixel.
        line(cx,cy,*hp,2)
        line(cx,cy,*mp,3); dot(cx,cy,3)

    date = day+'/'+month_number if language=='fr' else month_number+'/'+day
    if design=='horizon':
        time(31,11); centre_mono(weekday+' '+date,31,38,4)
        if twelve: tiny(ampm,50,28,5)
    elif design=='column':
        mono(hours,5,5,2,'monogram'); mono(minutes,5,29,3,'monogram')
        bounds=[i%64 for i,v in enumerate(pixels) if v in (2,3)]
        centre_mono(weekday,49,10,5); centre_mono(day,49,23,4); centre_mono(month,49,36,5)
        if twelve: tiny(ampm,_round((min(bounds)+max(bounds))/2-3),47,5)
    elif design=='week':
        time(31,2)
        if twelve: tiny(ampm,50,19,5)
        offset=at.weekday() if language=='fr' else (at.weekday()+1)%7
        first=at-timedelta(days=offset)
        initials=('L','M','M','J','V','S','D') if language=='fr' else ('S','M','T','W','T','F','S')
        for i in range(7):
            d=first+timedelta(days=i); selected=i==offset; x=1+i*9
            mono(initials[i],x+1,26,4 if selected else 5)
            tiny(f'{d.day:02}',x,36,3 if selected else 2 if d.month==at.month else 5)
            if selected:
                for j in range(1,6): dot(x+j,42,3)
        centre_mono(month+' '+str(at.year),31,47,4)
    elif design=='date-card':
        mono(weekday,4,4,5); mono(month,4,17,5); mono(day,37,5,4,'monogram'); time(31,33)
        if twelve: tiny(ampm,50,24,5)
    elif design=='meridian':
        ticks(24,25,21); hands(24,25,10,16)
        analog_text(weekday,55,7,5); analog_text(day,55,20,4,big=True); analog_text(month,55,35,5)
        if twelve: analog_text(ampm,55,46,5)
    elif design=='almanac':
        ticks(19,26,16); hands(19,26,7,12)
        analog_text(weekday,50,8,5); analog_text(day,50,20,4,scale=2,big=True); analog_text(month,50,40,5)
        if twelve: analog_text(ampm,19,47,5)
    else:
        if design=='halo': ticks(31,21,19,True); hands(31,21,9,15)
        elif design=='quadrant':
            for coordinates in geometry['square']: line(*coordinates)
            hands(31,21,9,15)
        else:
            for label,cx,y in (('12',31,2),('3',50,20),('6',31,37),('9',12,20)): analog_text(label,cx,y,5)
            for i,coordinates in enumerate(geometry['cardinal_ticks']):
                if i%3: dot(*coordinates,1)
            hands(31,22,8,13)
        analog_text(weekday+' '+day+' '+month,31,47,4)
        if twelve: analog_text(ampm,57,37,5)
    return bytes(pixels)


def render_frame(design, at, options=None):
    options=normalize_options(options)
    palette=_data()[0]['palettes'][options['palette']]
    return bytes(component for index in render_indices(design,at,options) for component in palette[index])


def build_packet(request):
    from .clocks import ClockPacket, clock_period, GUARD
    cadence=request.get('cadence','conservative');clock_period(cadence)
    design=request['clock_id']; options=normalize_options(request.get('options'))
    # Use integer centiseconds so a packet beginning mid-minute keeps the exact
    # remaining hold. Only clock-minute boundaries create new native frames.
    start,end=_round(float(request['display_at'])*100),_round(float(request['end_at'])*100)
    if design not in DESIGNS or not 0<end-start<=(clock_period(cadence)+GUARD)*100: raise ValueError('Invalid standard clock timeline')
    frames=[]; delays=[]; cursor=start
    while cursor<end:
        at=datetime.fromtimestamp((start if cadence=='minute' else cursor)/100)
        next_minute=(cursor//6000+1)*6000
        stop=end if cadence=='minute' else min(end,next_minute)
        frames.append(render_frame(design,at,options)); delays.append(stop-cursor); cursor=stop
    signature='standard-clock:'+hashlib.sha256(json.dumps({
        'id':design,'options':options,'start':start,'end':end,'cadence':cadence,
        'frames':[hashlib.sha256(frame).hexdigest() for frame in frames]},sort_keys=True).encode()).hexdigest()
    return ClockPacket(tuple(frames),tuple(delays),signature)
