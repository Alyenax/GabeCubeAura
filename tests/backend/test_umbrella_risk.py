"""Approved native umbrella, unchanged weather icons and bounded shared rails."""
from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image
from signalbar.faceplate import artwork_dashboard as dashboard
from signalbar.faceplate import player_city_row
from signalbar.faceplate.scenes import Canvas

APPROVED=('0011100','0111110','1111111','1001001','0001000','0101000','0011000')

class UmbrellaRiskTests(unittest.TestCase):
    def test_exact_approved_pixels_colour_and_dark_gutters(self):
        canvas=Canvas();dashboard._precipitation_risk_icon(canvas,30,48)
        expected={(30+x,47+y) for y,row in enumerate(APPROVED) for x,bit in enumerate(row) if bit=='1'}
        actual={(i%64,i//64) for i,colour in enumerate(canvas.pixels) if colour!=(0,0,0)}
        self.assertEqual(actual,expected)
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

    def test_umbrella_replaces_only_risk_seat_for_all_forecasts_and_city_uses_same_pixels(self):
        cases=0
        for ux in (False,True):
            for unit in ('celsius','fahrenheit'):
                for temp in (-100,-12,0,18,100,None):
                    for chance in (0,70,100,None):
                        forecast=dict(next_hour_condition='rain',next_hour_temperature_c=temp,next_hour_precipitation_probability=chance)
                        facts=dict(ux_enabled=ux,unit=unit,forecast=forecast)
                        before=Canvas();after=Canvas();seats=[]
                        def old_risk(canvas,x,y):
                            seats.append(x)
                            colours={'C':dashboard.SEPARATOR_GREY,'B':dashboard.WEATHER_BLUE}
                            for dy,line in enumerate(dashboard.RAIN_MARK):
                                for dx,bit in enumerate(line):
                                    if bit in colours:canvas.pixel(x-1+dx,y-2+dy,colours[bit])
                        with patch.object(dashboard,'_precipitation_risk_icon',old_risk):dashboard._draw_bottom_row(before,'next_hour',**facts)
                        dashboard._draw_bottom_row(after,'next_hour',**facts)
                        self.assertEqual(len(seats),1)
                        changed=[i for i,(a,b) in enumerate(zip(before.pixels,after.pixels)) if a!=b]
                        self.assertTrue(changed)
                        self.assertTrue(all(seats[0]<=i%64<=seats[0]+6 and 46<=i//64<=53 for i in changed))
                        city=player_city_row.build_rail(48213,dict(mode='dashboard',dashboard=dict(bottom_mode='next_hour',**facts)))
                        self.assertEqual(city,after.bytes()[45*64*3:]);cases+=1
        self.assertEqual(cases,96)
