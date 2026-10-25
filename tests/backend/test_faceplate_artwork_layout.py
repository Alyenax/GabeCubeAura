"""Lab 30 prepared artwork presentation tests without a Steam client."""
import unittest

from signalbar.faceplate.artwork_layout import (
    FRAME_BYTES, Logo, compose_frame, validate_layout,
)


class FaceplateArtworkLayoutTests(unittest.TestCase):
    def setUp(self):
        self.frame = bytes((25, 55, 85)) * (64 * 54)
        self.logo = Logo(2, 1, ((0, 0, 1.0, (255, 255, 255)),
                                (1, 0, 1.0, (255, 255, 255))))

    def test_style_art_keeps_original_bytes(self):
        self.assertEqual(compose_frame(self.frame, self.logo, "art"), self.frame)

    def test_missing_logo_never_produces_blank_picture(self):
        self.assertEqual(compose_frame(self.frame, None, "logo_only"), self.frame)

    def test_logo_only_clears_background_and_sets_logo(self):
        result = compose_frame(self.frame, self.logo, "logo_only", "top")
        self.assertEqual(len(result), FRAME_BYTES)
        self.assertEqual(result[:3], bytes((0, 0, 0)))
        i = 3 * (2 * 64 + 31)
        self.assertEqual(result[i:i+3], bytes((255, 255, 255)))

    def test_logo_positions_are_visibly_different(self):
        previews = {position: compose_frame(self.frame, self.logo, "logo", position)
                    for position in ("top", "centre", "bottom", "bottom_rail")}
        self.assertEqual(len(set(previews.values())), 4)

    def test_safe_bottom_never_enters_dashboard_status_rows(self):
        logo = Logo(2, 48, tuple(
            (x, y, 1.0, (255, 255, 255)) for y in range(48) for x in range(2)
        ))
        safe = compose_frame(bytes(FRAME_BYTES), logo, "logo", "bottom")
        replacement = compose_frame(bytes(FRAME_BYTES), logo, "logo", "bottom_rail")
        self.assertEqual(set(safe[45 * 64 * 3:]), {0})
        self.assertIn(255, replacement[45 * 64 * 3:])

    def test_dim_shade_is_brighter_in_logo_mode(self):
        plain = compose_frame(self.frame, self.logo, "logo", "bottom")
        shade = compose_frame(self.frame, self.logo, "logo_dim", "bottom")
        self.assertNotEqual(plain, shade)
        self.assertLess(shade[3 * (52 * 64)], plain[3 * (52 * 64)])

    def test_unknown_presentation_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_layout("glow", "top")
        with self.assertRaises(ValueError):
            validate_layout("art", "left")


if __name__ == "__main__":
    unittest.main()
