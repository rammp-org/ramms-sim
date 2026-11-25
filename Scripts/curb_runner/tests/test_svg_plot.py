"""svg_plot.py (no editor; nothing written outside a temporary folder).

    python -I Scripts/curb_runner/tests/test_svg_plot.py
"""

import math
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import svg_plot as sp  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"


def figure(**kw):
    xs = [i * 0.1 for i in range(101)]
    return sp.Figure("A title <&>", "distance (m)", [
        sp.Panel("pitch (deg)", [sp.Series("rider, on", xs, [math.sin(x) for x in xs], "on"),
                                 sp.Series("chassis, on", xs, [math.cos(x) for x in xs], "on", "second"),
                                 sp.Series("ground", xs, [0.5 for _ in xs], "ground")], refs=[0.0]),
        sp.Panel("state", [sp.Series("state", xs, [0 if x < 5 else 1 for x in xs], "off", step=True)],
                 y_range=(-0.4, 1.4), ticks=[(0, "Off"), (1, "Active")]),
    ], marks=[sp.Mark(4.0, "in > up"), sp.Mark(6.0, "assist on", "event")], spans=[sp.Span(3.7, 4.3)],
        names=[(0.0, 3.7, "in"), (4.3, 10.0, "up")], **kw)


class Ticks(unittest.TestCase):
    def test_round_steps(self):
        self.assertEqual(sp.nice_ticks(0.0, 10.0, 5), [0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
        self.assertEqual(sp.nice_ticks(-5.2, 5.1, 4), [-5.0, 0.0, 5.0])
        self.assertEqual(sp.nice_ticks(0.0, 0.07, 4), [0.0, 0.02, 0.04, 0.06])
        self.assertIn(3.0, sp.nice_ticks(3.0, 3.0))  # no range: ticks about the value
        self.assertEqual(sp.nice_ticks(10.0, 0.0, 5), sp.nice_ticks(0.0, 10.0, 5))
        self.assertEqual(sp.nice_ticks(None, 1.0), [0.0, 1.0])

    def test_fmt(self):
        self.assertEqual(sp.fmt(2.0), "2")
        self.assertEqual(sp.fmt(-0.5), "-0.5")
        self.assertEqual(sp.fmt(0.25), "0.25")

    def test_scale(self):
        self.assertEqual(sp.scale(5.0, 0.0, 10.0, 100.0, 200.0), 150.0)
        self.assertEqual(sp.scale(0.0, 0.0, 10.0, 200.0, 100.0), 200.0)  # a y axis runs upward


class Paths(unittest.TestCase):
    def test_a_gap_breaks_the_line(self):
        d = sp.path_of([0, 1, 2, 3, 4], [0.0, 1.0, None, 3.0, float("nan")], lambda x: x, lambda y: y)
        self.assertEqual(d.count("M"), 2)
        self.assertEqual(d.count("L"), 1)
        self.assertEqual(sp.path_of([0, 1], [None, None], lambda x: x, lambda y: y), "")

    def test_a_step_holds_its_value(self):
        d = sp.path_of([0, 1, 2], [0.0, 0.0, 5.0], lambda x: 10.0 * x, lambda y: y, step=True)
        self.assertEqual(d, "M0.0 0.0 L10.0 0.0 L10.0 0.0 L20.0 0.0 L20.0 5.0")  # across, then up at the change

    def test_thin_keeps_the_ends(self):
        xs = list(range(5000))
        a, b = sp.thin(xs, xs, 800)
        self.assertLessEqual(len(a), 801)
        self.assertEqual((a[0], a[-1]), (0, 4999))
        self.assertEqual(sp.thin([1, 2], [3, 4]), ([1, 2], [3, 4]))


class Render(unittest.TestCase):
    def test_well_formed_and_complete(self):
        svg = sp.render(figure())
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, NS + "svg")
        self.assertEqual(len(root.findall(NS + "g")), 2)  # a group per panel
        self.assertEqual(len([e for e in root.iter(NS + "path")]), 4)  # a path per line
        texts = [e.text for e in root.iter(NS + "text")]
        for want in ("A title <&>", "pitch (deg)", "state", "rider, on", "ground", "Off", "Active", "in", "up", "assist on",
                     "distance (m)"):
            self.assertIn(want, texts)
        self.assertNotIn("in > up", texts)  # a seam is named by the stretches either side, not on its line
        titles = [e.text for e in root.iter(NS + "title")]
        self.assertIn("in > up", titles)
        self.assertNotIn("nan", svg.lower().replace("span", ""))
        self.assertIn("prefers-color-scheme: dark", svg)  # both surfaces

    def test_the_x_axis_is_shared_and_exposed(self):
        root = ET.fromstring(sp.render(figure()))
        self.assertEqual(float(root.get("data-xmin")), 0.0)
        self.assertEqual(float(root.get("data-xmax")), 10.0)
        left, right = float(root.get("data-left")), float(root.get("data-right"))
        self.assertEqual((left, right), (sp.LEFT, sp.WIDTH - sp.RIGHT))
        # The mark at x = 4 of 0..10 is 40 % of the way across, in every panel.
        mark = next(e for e in root.iter(NS + "line") if e.get("class") == "sv-mark")
        self.assertAlmostEqual(float(mark.get("x1")), left + 0.4 * (right - left), places=1)
        self.assertEqual(float(mark.get("y1")), sp.TOP)
        event = next(e for e in root.iter(NS + "line") if e.get("class") == "sv-event")
        self.assertAlmostEqual(float(event.get("x1")), left + 0.6 * (right - left), places=1)

    def test_classes_carry_role_and_kind(self):
        root = ET.fromstring(sp.render(figure()))
        classes = sorted(e.get("class") for e in root.iter(NS + "path"))
        self.assertEqual(classes, ["sv-line sv-ground sv-main", "sv-line sv-off sv-main", "sv-line sv-on sv-main",
                                   "sv-line sv-on sv-second"])
        with self.assertRaises(ValueError):
            sp.Series("x", [0], [0], "purple")

    def test_the_first_listed_line_is_drawn_last(self):
        root = ET.fromstring(sp.render(figure()))
        first_panel = root.findall(NS + "g")[0]
        order = [e.find(NS + "title").text for e in first_panel.findall(NS + "path")]
        self.assertEqual(order, ["ground", "chassis, on", "rider, on"])  # the rider on top

    def test_at_least_three_y_ticks(self):
        xs = [0.0, 1.0]
        fig = sp.Figure("t", "x", [sp.Panel("roll", [sp.Series("a", xs, [-4.0, 4.0])])])
        root = ET.fromstring(sp.render(fig))
        ticks = [e.text for e in root.findall(NS + "g")[0].iter(NS + "text") if e.get("text-anchor") == "end"]
        self.assertGreaterEqual(len(ticks), 3)

    def test_an_empty_figure_still_renders(self):
        root = ET.fromstring(sp.render(sp.Figure("nothing", "x", [sp.Panel("p", [sp.Series("a", [], [])])])))
        self.assertEqual(root.tag, NS + "svg")

    def test_a_long_line_stays_small(self):
        xs = [i * 0.001 for i in range(20000)]
        svg = sp.render(sp.Figure("t", "x", [sp.Panel("p", [sp.Series("a", xs, [math.sin(x) for x in xs])])]))
        self.assertLess(len(svg), 40000)

    def test_write_is_atomic(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "sub", "f.svg")
            sp.write(p, sp.render(figure()))
            self.assertEqual(ET.parse(p).getroot().tag, NS + "svg")
            self.assertEqual(os.listdir(os.path.dirname(p)), ["f.svg"])  # no temporary file left
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
