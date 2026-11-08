"""Approved native rain mark, unchanged weather icons and bounded shared rails."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from signalbar.faceplate import artwork_dashboard as dashboard
from signalbar.faceplate import player_city_row
from signalbar.faceplate.scenes import Canvas
from signalbar.faceplate.weather_artwork import build_weather_artwork_dashboard_snapshot, build_weather_artwork_scene

APPROVED=tuple(json.loads((Path(__file__).resolve().parents[1]/'fixtures/rain-risk-approved.json').read_text())['rows'])

class RainRiskTests(unittest.TestCase):
    def test_exact_approved_pixels_colour_and_dark_gutters(self):
        canvas=Canvas();dashboard._precipitation_risk_icon(canvas,30,48)
        expected={(30+x,47+y) for y,row in enumerate(APPROVED) for x,bit in enumerate(row) if bit=='1'}
        actual={(i%64,i//64) for i,colour in enumerate(canvas.pixels) if colour!=(0,0,0)}
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),11)
        self.assertTrue(all(canvas.pixels[y*64+x]==dashboard.WEATHER_BLUE for x,y in actual))
        for y in range(45,54):
            self.assertEqual(canvas.pixels[y*64+29],(0,0,0));self.assertEqual(canvas.pixels[y*64+37],(0,0,0))
        self.assertTrue(all(canvas.pixels[46*64+x]==(0,0,0) for x in range(30,37)))

    def test_current_weather_icon_retains_its_approved_rain_pixels(self):
        canvas=Canvas();dashboard._weather_icon(canvas,'rain',10,47,compact=True)
        colour_map={'C':dashboard.SEPARATOR_GREY,'B':dashboard.WEATHER_BLUE}
        expected={(10+x-1,46+y):colour_map[bit] for y,row in enumerate(dashboard.RAIN_MARK) for x,bit in enumerate(row) if bit in colour_map}
        actual={(i%64,i//64):c for i,c in enumerate(canvas.pixels) if c!=(0,0,0)}
        self.assertEqual(actual,expected)

    def test_rain_replaces_only_risk_seat_for_all_forecasts_and_city_uses_same_pixels(self):
        cases=0
        for ux in (False,True):
            for unit in ('celsius','fahrenheit'):
                for temp in (-100,-12,0,18,100,None):
                    for chance in (0,30,70,100,None):
                        forecast=dict(next_hour_condition='rain',next_hour_temperature_c=temp,next_hour_precipitation_probability=chance)
                        facts=dict(ux_enabled=ux,unit=unit,forecast=forecast)
                        before=Canvas();after=Canvas();seats=[]
                        def old_risk(canvas,x,y):
                            seats.append(x)
                            previous=('0011100','0111110','1111111','1001001','0001000','0101000','0011000')
                            for dy,line in enumerate(previous):
                                for dx,bit in enumerate(line):
                                    if bit=='1':canvas.pixel(x+dx,y-1+dy,dashboard.WEATHER_BLUE)
                        with patch.object(dashboard,'_precipitation_risk_icon',old_risk):dashboard._draw_bottom_row(before,'next_hour',**facts)
                        dashboard._draw_bottom_row(after,'next_hour',**facts)
                        self.assertEqual(len(seats),1)
                        changed=[i for i,(a,b) in enumerate(zip(before.pixels,after.pixels)) if a!=b]
                        self.assertTrue(changed)
                        self.assertTrue(all(seats[0]<=i%64<=seats[0]+6 and 46<=i//64<=53 for i in changed))
                        city=player_city_row.build_rail(48213,dict(mode='dashboard',dashboard=dict(bottom_mode='next_hour',**facts)))
                        self.assertEqual(city,after.bytes()[45*64*3:]);cases+=1
        self.assertEqual(cases,120)

    def test_weather_dashboards_use_exact_shared_rain_row_and_keep_the_weather_animation(self):
        for theme in ('weather-artwork-v1','weather-artwork-v2'):
            for phase,hour in (('day',12),('night',22)):
                weather,_=build_weather_artwork_scene('rain',0,12,'celsius',phase,visual_theme=theme)
                with patch.object(dashboard,'PRECIPITATION_RISK_MARK',('0011100','0111110','1111111','1001001','0001000','0101000','0011000')):
                    previous,_=build_weather_artwork_dashboard_snapshot(
                        f'2026-10-26T{hour}:00:00','rain',0,12,'celsius',
                        '2026-10-26T07:30:00','2026-10-26T18:30:00',visual_theme=theme)
                for chance in (0,30,70,100,None):
                    forecast=dict(next_hour_condition='rain',next_hour_temperature_c=18,next_hour_precipitation_probability=chance)
                    row=Canvas();dashboard._draw_bottom_row(row,'next_hour',forecast=forecast,unit='celsius')
                    result,_=build_weather_artwork_dashboard_snapshot(
                        f'2026-10-26T{hour}:00:00','rain',0,12,'celsius',
                        '2026-10-26T07:30:00','2026-10-26T18:30:00',visual_theme=theme,forecast=forecast)
                    self.assertEqual(len(result.frames),len(weather.frames))
                    self.assertEqual(result.delays_cs or (result.delay_cs,)*len(result.frames),
                                     weather.delays_cs or (weather.delay_cs,)*len(weather.frames))
                    for frame,background in zip(result.frames,previous.frames):
                        self.assertEqual(frame[45*64*3:],row.bytes()[45*64*3:])
                        self.assertEqual(frame[:45*64*3],background[:45*64*3])
