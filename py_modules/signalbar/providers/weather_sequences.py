"""Deterministic weather loops for GabeCubeAura's 17 physical LEDs.

Weather stays a background colour field with small, repeatable motion. No
temperature pixels, external state, device access, or network calls live here.
"""

from __future__ import annotations

import math

LED_COUNT = 17
CLOUD_CROSS_GATHER_SECONDS = 20.0
CLOUD_SLOW_CONVERGENCE_SECONDS = 48.0
NIGHT = [0, 8, 38]
NIGHT_CLOUD = [35, 35, 35]
MOON_WHITES = ([128, 128, 128], [192, 192, 192], [255, 255, 255])
CLEAR_NIGHT_MOON_WHITES = ([112, 112, 112], [168, 168, 168], [224, 224, 224])


def weather_loop_seconds(condition, variant):
    if condition in {"cloud", "cloud_night"} and variant == 2:
        return CLOUD_CROSS_GATHER_SECONDS
    if condition in {"cloud", "cloud_night"} and variant == 3:
        return CLOUD_SLOW_CONVERGENCE_SECONDS
    if condition == "clear_night" and variant == 0:
        return 6.0
    return 8.0

# Fixed, irregular timing makes the ripple repeatable in previews and tests.
RAIN_EVENTS = (
    ((5,.30),(11,1.10),(7,1.84),(3,2.55),(13,2.55),(9,3.38),
     (6,4.12),(12,4.88),(4,5.70),(10,5.70),(8,6.52),(13,7.22)),
    ((8,.30),(4,1.08),(12,1.84),(6,2.60),(13,2.60),(10,3.36),
     (3,4.14),(7,4.90),(12,5.64),(5,5.64),(9,6.48),(14,7.22)),
)
SNOW_GAPS = (
    ((3,12),.35), ((8,),1.20), ((5,14),2.05), ((10,),2.92),
    ((1,7),3.80), ((13,),4.68), ((4,15),5.50), ((9,),6.38),
    ((2,11),7.15),
)
SNOW_ORDER = (8,3,13,5,10,1,15,6,11,0,16,4,12,7,14,2,9)
SNOW_EVENTS = (
    (8,.18),(3,.49),(12,.72),(6,1.07),(15,1.27),(5,1.53),
    (11,1.84),(2,1.84),(9,2.23),(13,2.50),(4,2.78),(8,3.03),
    (14,3.26),(6,3.63),(10,3.91),(1,4.19),(12,4.19),(7,4.55),
    (15,4.83),(3,5.06),(9,5.42),(5,5.63),(11,5.92),(2,6.21),
    (14,6.21),(8,6.61),(4,6.88),(12,7.10),(6,7.35),(10,7.62),
)


def clamp(value):
    return max(0, min(255, round(value)))


def smooth(start, end, value):
    fraction = max(0, min(1, (value-start)/(end-start)))
    return fraction*fraction*(3-2*fraction)


def mix(first, second, fraction):
    return [clamp(a+(b-a)*fraction) for a,b in zip(first,second)]


def pulse(time, at, width):
    return max(0, 1-abs(time-at)/width)


def add(frame, index, colour, power):
    if 0 <= index < LED_COUNT:
        frame[index] = [clamp(a+b*power) for a,b in zip(frame[index],colour)]


def glow(frame, centre, colour, spread, power):
    for index in range(LED_COUNT):
        weight = math.exp(-((index-centre)/spread)**2*.85)*power
        if weight > .01:
            add(frame,index,colour,weight)


def _sun(frame, variant, time):
    # The two beta.9 sun scenes were approved unchanged.
    if variant == 0:
        rays = (-2+time*2.75,18-time*2.75,(time*2.75+9)%22-2)
        for index in range(LED_COUNT):
            shimmer = max(0,math.sin(time*math.pi+index*1.87))**6
            pixel = mix([212,152,0],[234,184,8],.18+.48*shimmer)
            for ray,strength in zip(rays,(1,1,.67)):
                distance = abs(index-ray)
                shoulder = math.exp(-(distance/1.75)**2*1.1)*strength
                glint = math.exp(-(distance/.7)**2*1.2)*strength
                pixel = mix(pixel,[248,214,49],shoulder*.45)
                pixel = mix(pixel,[255,245,174],glint*.92)
            frame[index] = pixel
    else:
        bloom = (1-math.cos(time*math.pi/4))/2
        radius = 1.2+6.6*bloom
        for index in range(LED_COUNT):
            distance = abs(index-8)
            field = smooth(radius+1.25,radius-1.15,distance)
            pixel = mix([216,161,0],[247,208,36],field*.52)
            frame[index] = mix(pixel,[255,239,151],field*(.48+.39*bloom)*(1-distance/45))


def _night_base(frame):
    for index in range(LED_COUNT):
        frame[index] = NIGHT[:]


def _moon_white_step(value, whites=MOON_WHITES):
    if value < .28:
        return NIGHT
    if value < .58:
        return whites[0]
    if value < .84:
        return whites[1]
    return whites[2]


def _moon(frame, variant, time):
    """Transpose the approved daytime clear-sky choreography to night."""
    _night_base(frame)
    if variant == 0:  # Breathing moon, transposed from the Sun glints slot.
        breath = (1 - math.cos(time * math.pi / 3)) / 2
        core = _moon_white_step(.72 + .28 * breath, CLEAR_NIGHT_MOON_WHITES)
        halo = _moon_white_step(.18 + .66 * breath, CLEAR_NIGHT_MOON_WHITES)
        frame[8] = core[:]
        frame[9] = core[:]
        if breath > .16:
            frame[7] = halo[:]
            frame[10] = halo[:]
        return

    # Lunar bloom keeps Solar bloom's centred expansion and contraction.
    bloom = (1 - math.cos(time * math.pi / 4)) / 2
    radius = 1.2 + 6.6 * bloom
    for index in range(LED_COUNT):
        distance = abs(index - 8)
        field = smooth(radius + 1.25, radius - 1.15, distance)
        if field > .12:
            frame[index] = _moon_white_step(.35 + .65 * field, CLEAR_NIGHT_MOON_WHITES)[:]


def _rain(frame, variant, time):
    bluewater = variant == 0
    background = [0,45,112] if bluewater else [66,68,70]
    for index in range(LED_COUNT):
        frame[index] = background[:]

    def crest(origin,radius,width,power,colour):
        for index in range(LED_COUNT):
            weight = math.exp(-1.35*((abs(index-origin)-radius)/width)**2)*power
            if weight > .035:
                add(frame,index,colour,weight)

    for event_index,(position,at) in enumerate(RAIN_EVENTS[variant]):
        age = time-at
        if not -.07 <= age <= .5:
            continue
        if age < 0:
            glow(frame,position,[21,100,126] if bluewater else [8,76,170],.43,smooth(-.07,0,age)*.32)
        if 0 <= age < .12:
            # Pearl Rain keeps its white contact flash at half the previous level.
            glow(frame,position,[219,192,138] if bluewater else [82,108,116],.49,
                 (1-smooth(.02,.12,age))*.96)
        for delay,duration,reach,width,power,colour in (
            (.055,.335,1.9,.56,1,[40,119,133] if bluewater else [8,105,233]),
            (.16,.34,1.35,.53,.54,[34,91,125] if bluewater else [4,74,183]),
        ):
            progress = (age-delay)/duration
            if 0 < progress < 1:
                radius = .25+reach*(1-(1-progress)**1.35)
                envelope = math.sin(math.pi*progress)*(1-progress)**.32*power
                crest(position,radius,width,envelope,colour)
        if not bluewater and .08 <= age < .31:
            # One extra clearly blue pixel per impact, offset from the white
            # contact point; alternate its side rather than making a garland.
            accent = position+(2 if event_index%2 else -2)
            strength = smooth(.08,.13,age)*(1-smooth(.24,.31,age))
            if 0 <= accent < LED_COUNT:
                frame[accent] = mix(frame[accent],[18,99,238],strength*.90)
    return frame


def _cloud_point(frame, index, intensity):
    """Draw a neutral-white pixel; overlapping clouds keep the brighter one."""
    if 0 <= index < LED_COUNT:
        level = clamp(242 * max(0, min(1, intensity)))
        frame[index] = [max(frame[index][0], level)] * 3


def _cloud_cluster(frame, centre, width, levels):
    left = math.floor(centre - (width - 1) / 2 + .5)
    for offset in range(width):
        _cloud_point(frame, left + offset, levels[offset])


def _crossing_clouds(frame, time):
    age = time % 4.4
    envelope = min(1, age / .45, (4.4 - age) / .45)
    _cloud_cluster(frame, 1 + age * 3.5, 2, (.74 * envelope, .9 * envelope))
    _cloud_cluster(frame, 15 - age * 3.5, 2, (.95 * envelope, .68 * envelope))


def _cross_and_gather(frame, time):
    # Preserve the approved choreography while giving each crossing and
    # gathering beat more time to be legible on the physical diffuser.
    time *= 11 / CLOUD_CROSS_GATHER_SECONDS
    _crossing_clouds(frame, time)
    if time < 3.3:
        progress = max(0, (time - 1.45) / 1.85)
        if progress:
            _cloud_cluster(frame, 2 + progress * 6, 2, (.61, .85))
            _cloud_cluster(frame, 14 - progress * 6, 2, (.84, .64))
        return

    age = time - 3.3
    centre = 8 + 3.2 * math.sin(age * 1.06)
    accent = 0
    for at, side in ((.9, -1), (2.3, 1), (3.75, -1), (5.1, 1), (6.5, -1)):
        arrival = age - at
        if 0 <= arrival < 1.05:
            start = centre + side * 4.6
            position = start + (centre - start) * min(1, arrival / 1.05)
            _cloud_point(frame, math.floor(position + .5), .65 + .22 * math.sin(math.pi * arrival / 1.05))
            if arrival > .79:
                accent = .18
    _cloud_cluster(frame, centre, 3, (.71 + accent, .96, .76 + accent))


def _slow_convergence(frame, time):
    if time < 2:
        # Two small clouds approach from opposite sides before merging.
        _cloud_point(frame, math.floor(2 + time * 2.25 + .5), .76)
        _cloud_point(frame, math.floor(14 - time * 2.25 + .5), .93)
        return

    if time < 15:
        # One additional LED joins every ~1.9 seconds, up to eight. A small
        # incoming point alternates sides; it never makes a ninth LED.
        growth = (time - 2) / (13 / 7)
        width = min(8, 2 + math.floor(growth))
        centre = 8 + .5 * math.sin(time * .4)
        levels = [min(.94, .64 + .28 * (1 - abs(i - (width - 1) / 2) / 5)
                      + .035 * math.sin(time * 1.3 + i)) for i in range(width)]
        _cloud_cluster(frame, centre, width, levels)
        if width < 8:
            progress = growth % 1
            side = -1 if math.floor(growth) % 2 else 1
            start = centre + side * 7
            destination = centre + side * (width / 2 + .5)
            position = start + (destination - start) * min(1, progress / .94)
            _cloud_point(frame, math.floor(position + .5), .72 * smooth(0, .2, progress))
        return

    if time < 25:
        centre = 8 - (time - 15) * .45  # Eight LEDs reach the left edge.
    elif time < 39:
        centre = 3.5 + (time - 25) * (9 / 14)  # Then the right edge.
    else:
        centre = 12.5 + (time - 39)  # Exit completely beyond the right edge.
    levels = [.67 + .25 * (1 - abs(i - 3.5) / 4)
              + .035 * math.sin(time * .68 + i * .75) for i in range(8)]
    _cloud_cluster(frame, centre, 8, levels)


def _cloud(frame, variant, time):
    if variant == 2:
        _cross_and_gather(frame, time)
        return
    if variant == 3:
        _slow_convergence(frame, time)
        return

    # Keep the two 0.6.0 cloud patterns unchanged for existing selections.
    def shadow(centre,power=1):
        for index in range(LED_COUNT):
            dip = math.exp(-((index-centre)/3.1)**2)*117*power
            edge = math.exp(-((index-(centre-3.2))/.95)**2)*22*power
            level = clamp(frame[index][0]-dip+edge)
            frame[index] = [level]*3

    for index in range(LED_COUNT):
        level = clamp(172+8*math.sin(time*.55+index*.22))
        frame[index] = [level]*3
    if variant == 0:
        shadow(-5+time*3.25)
    elif variant == 1:
        # Two distinct passes, not a central collision or a reversing bounce.
        if .2 <= time < 3.65:
            envelope = smooth(.2,.7,time)*(1-smooth(3.15,3.65,time))
            shadow(-4+(time-.2)*4.2,envelope)
        if 4.0 <= time < 7.8:
            envelope = smooth(4.0,4.55,time)*(1-smooth(7.25,7.8,time))
            shadow(21-(time-4)*3.75,envelope)


def _night_cloud_point(frame, index, intensity):
    if 0 <= index < LED_COUNT:
        frame[index] = (NIGHT if intensity < .2 else NIGHT_CLOUD)[:]


def _night_cloud_cluster(frame, centre, width, levels):
    left = math.floor(centre - (width - 1) / 2 + .5)
    for offset in range(width):
        _night_cloud_point(frame, left + offset, levels[offset])


def _night_crossing_clouds(frame, time):
    age = time % 4.4
    envelope = min(1, age / .45, (4.4 - age) / .45)
    _night_cloud_cluster(frame, 1 + age * 3.5, 2, (.74 * envelope, .9 * envelope))
    _night_cloud_cluster(frame, 15 - age * 3.5, 2, (.95 * envelope, .68 * envelope))


def _night_cross_and_gather(frame, time):
    time *= 11 / CLOUD_CROSS_GATHER_SECONDS
    _night_crossing_clouds(frame, time)
    if time < 3.3:
        progress = max(0, (time - 1.45) / 1.85)
        if progress:
            _night_cloud_cluster(frame, 2 + progress * 6, 2, (.61, .85))
            _night_cloud_cluster(frame, 14 - progress * 6, 2, (.84, .64))
        return
    age = time - 3.3
    centre = 8 + 3.2 * math.sin(age * 1.06)
    accent = 0
    for at, side in ((.9, -1), (2.3, 1), (3.75, -1), (5.1, 1), (6.5, -1)):
        arrival = age - at
        if 0 <= arrival < 1.05:
            start = centre + side * 4.6
            position = start + (centre - start) * min(1, arrival / 1.05)
            _night_cloud_point(
                frame, math.floor(position + .5),
                .65 + .22 * math.sin(math.pi * arrival / 1.05),
            )
            if arrival > .79:
                accent = .18
    _night_cloud_cluster(frame, centre, 3, (.71 + accent, .96, .76 + accent))


def _night_slow_convergence(frame, time):
    if time < 2:
        _night_cloud_point(frame, math.floor(2 + time * 2.25 + .5), .76)
        _night_cloud_point(frame, math.floor(14 - time * 2.25 + .5), .93)
        return
    if time < 15:
        growth = (time - 2) / (13 / 7)
        width = min(8, 2 + math.floor(growth))
        centre = 8 + .5 * math.sin(time * .4)
        levels = [min(.94, .64 + .28 * (1 - abs(i - (width - 1) / 2) / 5)
                      + .035 * math.sin(time * 1.3 + i)) for i in range(width)]
        _night_cloud_cluster(frame, centre, width, levels)
        if width < 8:
            progress = growth % 1
            side = -1 if math.floor(growth) % 2 else 1
            start = centre + side * 7
            destination = centre + side * (width / 2 + .5)
            position = start + (destination - start) * min(1, progress / .94)
            _night_cloud_point(frame, math.floor(position + .5), .72 * smooth(0, .2, progress))
        return
    if time < 25:
        centre = 8 - (time - 15) * .45
    elif time < 39:
        centre = 3.5 + (time - 25) * (9 / 14)
    else:
        centre = 12.5 + (time - 39)
    levels = [.67 + .25 * (1 - abs(i - 3.5) / 4)
              + .035 * math.sin(time * .68 + i * .75) for i in range(8)]
    _night_cloud_cluster(frame, centre, 8, levels)


def _cloud_night(frame, variant, time):
    """Night palette with the unchanged four cloudy choreographies."""
    if variant == 2:
        _night_base(frame)
        _night_cross_and_gather(frame, time)
        return
    if variant == 3:
        _night_base(frame)
        _night_slow_convergence(frame, time)
        return

    _night_base(frame)

    def cloud(centre, power=1):
        for index in range(LED_COUNT):
            presence = math.exp(-((index - centre) / 3.1) ** 2) * power
            if presence > .12:
                frame[index] = NIGHT_CLOUD[:]

    if variant == 0:
        cloud(-5 + time * 3.25)
    elif variant == 1:
        if .2 <= time < 3.65:
            cloud(-4 + (time - .2) * 4.2, smooth(.2, .7, time) * (1 - smooth(3.15, 3.65, time)))
        if 4 <= time < 7.8:
            cloud(21 - (time - 4) * 3.75, smooth(4, 4.55, time) * (1 - smooth(7.25, 7.8, time)))


def _partly_cloudy(frame, variant, time, night):
    opening = smooth(.75,2.35,time)*(1-smooth(4.7,6.75,time))
    if night:
        _night_base(frame)
        for index in range(LED_COUNT):
            cloud = (.62 + .04 * math.sin(index * .38 + time * .42)
                     + .025 * math.cos(index * .83 - time * .27))
            cloud *= 1 - opening if variant == 1 else 1
            if cloud > .1:
                frame[index] = NIGHT_CLOUD[:]
        for index in range(LED_COUNT):
            distance = abs(index - 8)
            signal = opening * math.exp(-(distance / (1.2 + 2.3 * opening)) ** 2)
            if signal >= .28:
                frame[index] = _moon_white_step(.55 + .45 * signal)[:]
        return

    # Variant 0 retains the original cloud-and-light scene. In variant 1 the
    # same neutral-white cloud field fades all the way to black as the light
    # opens. Never substitute dark brown/blue for a dimmed cloud: those hues
    # are amplified unpredictably by the Steam Machine's diffuser.
    for index in range(LED_COUNT):
        white = 117 + 6*math.sin(index*.38+time*.42) + 3*math.cos(index*.83-time*.27)
        level = clamp(white*(1-opening if variant == 1 else 1))
        frame[index] = [level]*3

    # Only sufficiently bright, recognisably yellow/ivory light is drawn.
    # A weak warm tail would look red on the physical LEDs, so its pixels
    # remain neutral cloud (or black in the fade-out variant) instead.
    # Keep red and green almost equal: an amber red-heavy edge reads as red
    # once global Weather brightness and the physical diffuser are involved.
    colour = [250,246,45]
    for index in range(LED_COUNT):
        distance = abs(index-8)
        signal = opening*math.exp(-(distance/(1.2+2.3*opening))**2)
        if signal < .28:
            continue
        strength = .72+.28*smooth(.28,1,signal)
        frame[index] = [clamp(channel*strength) for channel in colour]


def _snow(frame, variant, time):
    if variant == 1:  # Snow takes hold: restore the accumulating beta.9 scene.
        for position,index in enumerate(SNOW_ORDER):
            age = time-(1.2+position*.275)
            white = (0 if age < 0 else 205 if age < .25 else
                     205*(1-smooth(.25,.48,age)) if age < .48 else
                     0 if age < .78 else 171*smooth(.78,.96,age))
            white = clamp((white+(192-white)*smooth(6.6,7.02,time))
                          *(1-smooth(7.35,8,time)))
            frame[index] = [white]*3
        if time < 6.6:
            for index,at in SNOW_EVENTS:
                age = time-at
                if 0 <= age < .34:
                    white = 225 if age < .09 else 196
                    if white > frame[index][0]:
                        frame[index] = [white]*3
        return
    # One soft white bed. Groups of two missing flakes alternate with single
    # ones; every gap fades out and refills before the next full loop.
    for index in range(LED_COUNT):
        frame[index] = [138]*3
    for positions,at in SNOW_GAPS:
        fade = smooth(at,at+.18,time)*(1-smooth(at+.47,at+.78,time))
        for index in positions:
            level = clamp(138*(1-.96*fade))
            frame[index] = [level]*3


def _storm(frame, variant, time):
    for index in range(LED_COUNT):
        frame[index] = [19,19,19]

    def bolt(at,width,positions,strength=1):
        power = pulse(time,at,width)*strength
        if power <= 0:
            return
        for index in range(LED_COUNT):
            intensity = power if index in positions else power*.42 if any(abs(x-index)==1 for x in positions) else power*.11
            frame[index] = mix(frame[index],[250,250,250],intensity)

    if variant == 0:  # Pulse and echoes, now with another full lightning phrase.
        bolt(.72,.13,(3,4,5,7));bolt(1.12,.13,(10,12,13,14))
        bolt(1.48,.25,(5,11),.29);bolt(1.87,.31,(2,13),.17)
        bolt(4.18,.13,(2,5,6,9));bolt(4.57,.12,(10,11,14,15),.88)
        bolt(4.93,.24,(4,12),.30);bolt(5.30,.31,(3,14),.17)
    else:  # Storm Break, retained.
        bolt(.72,.1,(2,4,6,7,10,12,14));bolt(1.12,.11,(1,3,5,8,9,11,15),.94)
        bolt(4.64,.12,(3,5,8,11,13),.64);bolt(4.97,.13,(2,6,9,12,15),.55)
    for index,pixel in enumerate(frame):
        level = max(pixel)
        frame[index] = [level]*3 if level >= 30 else [0,0,0]


def weather_sequence(condition, variant, time):
    """Return one logical RGB frame, before Weather-only brightness/cutoff."""
    frame = [[0,0,0] for _ in range(LED_COUNT)]
    time = max(0, time) % weather_loop_seconds(condition, variant)
    if condition == "clear_day":
        _sun(frame,variant,time)
    elif condition == "clear_night":
        _moon(frame,variant,time)
    elif condition == "rain":
        frame = _rain(frame,variant,time)
    elif condition == "cloud":
        _cloud(frame,variant,time)
    elif condition == "cloud_night":
        _cloud_night(frame,variant,time)
    elif condition in ("breaks","breaks_night"):
        _partly_cloudy(frame,variant,time,condition == "breaks_night")
    elif condition == "snow":
        _snow(frame,variant,time)
    else:
        _storm(frame,variant,time)
    return frame
