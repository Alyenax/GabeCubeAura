"""Count Only keeps unit precision; every count layout retains the City smile."""
import unittest
from signalbar.faceplate import player_city_row as row
from signalbar.faceplate.scenes import Canvas,draw_text,measure_text
from signalbar.faceplate.playtime import timer_facts
from signalbar.faceplate.player_city import rail_layout,DIGITS


class PlayerCount236(unittest.TestCase):
    def test_count_only_exact_native_digits_through_the_largest_steam_value(self):
        for players in (0,999,1000,1001,12345,48213,999999,1000000,4294967295):
            with self.subTest(players=players):
                text,width=rail_layout(players);self.assertEqual(text,format(players,','));x=(64-width-9)//2
                expected=Canvas(row.BACKGROUND)
                for dy,line in enumerate(row.SMILE):
                    for dx,bit in enumerate(line):
                        if bit=='1':expected.pixel(x+dx,46+dy,row.ACCENT)
                cursor=x+9
                for char in text:
                    if char==',':
                        for dy,line in enumerate(DIGITS[char]):
                            for dx,bit in enumerate(line):
                                if bit=='1':expected.pixel(cursor+dx,48+dy,row.WHITE)
                        cursor+=3
                    else:
                        draw_text(expected,cursor,48,char,row.WHITE);cursor+=4
                self.assertEqual(row.build_rail(players,{'mode':'count'}),expected.bytes()[45*64*3:])

    def test_us_thousands_example_has_a_real_comma_descender_and_dark_gutters(self):
        self.assertEqual(rail_layout(48213),('48,213',22))
        rail=row.build_rail(48213,{'mode':'count'})
        def pixel(x,y):
            at=((y-45)*64+x)*3
            return rail[at:at+3]
        self.assertEqual(pixel(34,52),bytes(row.WHITE))
        self.assertEqual(pixel(33,53),bytes(row.WHITE))
        for x in (32,35):
            for y in range(48,54):self.assertEqual(pixel(x,y),bytes(row.BACKGROUND))

    def test_smile_survives_every_count_mode_timer_and_long_value(self):
        cases=[dict(mode='controllers',percent=p,battery_style=s) for p in (None,100) for s in ('bar','percent')]
        cases += [dict(mode='session',session_minutes=m) for m in (None,125,999999999)]
        cases += [dict(mode='total',total_minutes=m) for m in (None,12345,999999999)]
        cases += [dict(mode='count'),dict(mode='achievements',achieved=999999,achievements_total=999999)]
        cases += [dict(countdown=c) for c in (timer_facts(59),timer_facts(300),timer_facts(9999*60),{'state':'ended'})]
        for players in (999,12345,4294967295):
            for facts in cases:
                with self.subTest(players=players,facts=facts):
                    rail=row.build_rail(players,facts)
                    pixels=[rail[p:p+3] for p in range(0,len(rail),3)]
                    columns=[n%64 for n,c in enumerate(pixels) if c==bytes(row.ACCENT)]
                    self.assertTrue(columns,'Known City smile colour remains')
                    left=min(columns)
                    for dy,line in enumerate(row.SMILE):
                        for dx,bit in enumerate(line):
                            if bit=='1':self.assertEqual(pixels[(dy+1)*64+left+dx],bytes(row.ACCENT))
                    self.assertEqual(len(rail),1728)


if __name__=='__main__':unittest.main()
