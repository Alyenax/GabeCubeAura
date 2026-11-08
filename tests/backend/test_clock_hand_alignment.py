"""Approved thin shared-pivot analog hands, independent of transfer cadence."""
from datetime import datetime
import unittest
from signalbar.faceplate.clock_standard import render_indices
from signalbar.backend.engine import faceplate_scene_cache_namespace

DIALS={'meridian':(24,25,10),'halo':(31,21,9),'almanac':(19,26,7),'quadrant':(31,21,9),'cardinal':(31,22,8)}


class HandAlignmentTests(unittest.TestCase):
    def test_1805_hour_hand_is_one_centre_column_without_right_offset(self):
        for design,(cx,cy,length) in DIALS.items():
            with self.subTest(design=design):
                pixels=render_indices(design,datetime(2026,10,27,18,5))
                for y in range(cy+1,cy+length+1):
                    self.assertEqual(2,pixels[y*64+cx])
                    self.assertEqual(0,pixels[y*64+cx-1])
                    self.assertEqual(0,pixels[y*64+cx+1])
                self.assertEqual(3,pixels[cy*64+cx])

    def test_overlapping_vertical_hands_keep_minute_colour_and_no_asymmetric_cap(self):
        for design,(cx,cy,_) in DIALS.items():
            with self.subTest(design=design):
                pixels=render_indices(design,datetime(2026,10,27,12,0))
                self.assertEqual(3,pixels[cy*64+cx])
                self.assertEqual(3,pixels[(cy-1)*64+cx])
                self.assertEqual(0,pixels[cy*64+cx-1])
                self.assertEqual(0,pixels[cy*64+cx+1])

    def test_old_clock_cache_namespace_is_not_reused(self):
        for design in DIALS:
            namespace=faceplate_scene_cache_namespace({'kind':'clock','clock_id':design})
            self.assertIn('fine-centred',namespace)
            self.assertNotEqual('gabecubeaura:encoded-rgb-peak-1:clock:native-clock-projection-v1',namespace)


if __name__=='__main__':unittest.main()
