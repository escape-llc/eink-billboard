import unittest

from ..model.color_theme import ColorTheme

class TestColorTheme(unittest.TestCase):
    def test_triadic_colors(self):
        ct = ColorTheme('triadic',10, 85, 50)
        p, s1, s2 = ct.colors()
        self.assertEqual(p, 'hsl(10, 85%, 50%)')
        self.assertEqual(s1, 'hsl(130, 85%, 50%)')
        self.assertEqual(s2, 'hsl(250, 85%, 50%)')

    def test_analogous_colors_and_angle(self):
        ct = ColorTheme('analogous', 10, 85, 50, angle_adj=30)
        p, s1, s2 = ct.colors()
        self.assertEqual(p, 'hsl(10, 85%, 50%)')
        self.assertEqual(s1, 'hsl(340, 85%, 50%)')
        self.assertEqual(s2, 'hsl(40, 85%, 50%)')

    def test_split_complementary_colors(self):
        ct = ColorTheme('split-complementary', 10, 85, 50)
        p, s1, s2 = ct.colors()
        self.assertEqual(p, 'hsl(10, 85%, 50%)')
        self.assertEqual(s1, 'hsl(160, 85%, 50%)')
        self.assertEqual(s2, 'hsl(220, 85%, 50%)')

    def test_monochrome_colors(self):
        ct = ColorTheme('monochrome', 200, sat=60, light=40)
        p, s1, s2 = ct.colors()
        self.assertEqual(p, 'hsl(200, 60%, 40%)')
        self.assertEqual(s1, 'hsl(200, 60%, 40%)')
        self.assertEqual(s2, 'hsl(200, 60%, 40%)')

    def test_to_css_vars_and_string(self):
        ct = ColorTheme('triadic', 15, 80, 45, 25)
        vars = ct.to_css_vars()
        self.assertIn('--theme-h', vars)
        self.assertEqual(vars['--theme-h'], '15')
        self.assertEqual(vars['--theme-s'], '80%')
        self.assertEqual(vars['--theme-param-1'], '25.0')
        self.assertIn('--color-primary-hue', vars)
        # css_vars_string should contain assignments
        s = ct.css_vars_string()
        self.assertIn('--theme-h: 15', s)

    def test_invalid_sat_raises(self):
        with self.assertRaises(ValueError):
            ColorTheme('triadic', 10, sat=-1, light=50)
        with self.assertRaises(ValueError):
            ColorTheme('triadic', 10, sat=101, light=50)

    def test_invalid_light_raises(self):
        with self.assertRaises(ValueError):
            ColorTheme('triadic', 10, sat=50, light=-0.1)
        with self.assertRaises(ValueError):
            ColorTheme('triadic', 10, sat=50, light=100.1)

    def test_invalid_scheme_raises(self):
        with self.assertRaises(ValueError):
            ColorTheme('invalid-scheme', 10, sat=50, light=50)


if __name__ == '__main__':
    unittest.main()
