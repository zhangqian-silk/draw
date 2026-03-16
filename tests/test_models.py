import unittest

from drawbot.models import DrawPlan, Point, Region, Stroke, default_reveal_ratio


class RegionTests(unittest.TestCase):
    def test_region_parser(self) -> None:
        region = Region.parse("10,20,300,400")
        self.assertEqual((region.left, region.top, region.width, region.height), (10, 20, 300, 400))

    def test_region_exposes_aspect_ratio(self) -> None:
        region = Region(left=10, top=20, width=300, height=150)
        self.assertAlmostEqual(region.aspect_ratio, 2.0)

    def test_region_parser_rejects_invalid_size(self) -> None:
        with self.assertRaises(ValueError):
            Region.parse("10,20,0,400")

    def test_screen_mapping_uses_padding(self) -> None:
        region = Region(left=100, top=200, width=500, height=300)
        x, y = region.to_screen_point(Point(50, 50), padding_ratio=0.1)
        self.assertEqual((x, y), (350, 350))


class DrawPlanTests(unittest.TestCase):
    def test_default_reveal_ratio(self) -> None:
        self.assertAlmostEqual(default_reveal_ratio("medium"), 1.0)

    def test_trimmed_keeps_partial_plan(self) -> None:
        plan = DrawPlan(
            word="cat",
            difficulty="medium",
            description="simple cat outline",
            hidden_features=("whiskers",),
            strokes=(
                Stroke(name="body", points=(Point(0, 0), Point(50, 0), Point(50, 50))),
                Stroke(name="tail", points=(Point(70, 30), Point(90, 10), Point(95, 40))),
            ),
        )

        trimmed = plan.trimmed(0.5)

        self.assertEqual(len(trimmed.strokes), 1)
        self.assertEqual(len(trimmed.strokes[0].points), 3)

    def test_from_payload_clamps_coordinates(self) -> None:
        payload = {
            "word": "bird",
            "difficulty": "hard",
            "description": "partial bird",
            "hidden_features": ["wing detail"],
            "strokes": [
                {
                    "name": "outline",
                    "points": [{"x": -10, "y": 5}, {"x": 150, "y": 95}],
                }
            ],
        }

        plan = DrawPlan.from_payload(payload)

        self.assertEqual(plan.strokes[0].points[0], Point(0.0, 5.0))
        self.assertEqual(plan.strokes[0].points[1], Point(100.0, 95.0))

    def test_from_payload_uses_prompt_when_present(self) -> None:
        payload = {
            "prompt": "draw a sleepy cat curled into a ball",
            "word": "sleepy cat",
            "difficulty": "medium",
            "description": "curled outline with ears",
            "hidden_features": [],
            "strokes": [
                {
                    "name": "outline",
                    "points": [{"x": 10, "y": 20}, {"x": 70, "y": 65}],
                }
            ],
        }

        plan = DrawPlan.from_payload(payload)

        self.assertEqual(plan.prompt, "draw a sleepy cat curled into a ball")

    def test_from_payload_supports_svg_only(self) -> None:
        payload = {
            "prompt": "draw a house",
            "word": "house",
            "difficulty": "medium",
            "description": "",
            "hidden_features": [],
            "svg": """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
              <rect x="0" y="0" width="100" height="100" fill="white" stroke="none" />
              <path d="M20 60 L50 30 L80 60" stroke="black" fill="none" />
              <rect x="28" y="60" width="44" height="24" stroke="black" fill="none" />
            </svg>
            """,
        }

        plan = DrawPlan.from_payload(payload)

        self.assertTrue(plan.svg.strip().startswith("<svg"))
        self.assertGreaterEqual(len(plan.strokes), 2)

    def test_as_payload_round_trips_svg(self) -> None:
        plan = DrawPlan.from_svg(
            svg="""
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
              <rect x="0" y="0" width="100" height="100" fill="white" stroke="none" />
              <circle cx="50" cy="50" r="20" stroke="black" fill="none" />
            </svg>
            """,
            prompt="draw a circle",
            difficulty="medium",
            word="circle",
        )

        restored = DrawPlan.from_payload(plan.as_payload())

        self.assertEqual(restored.word, "circle")
        self.assertTrue(restored.svg.strip().startswith("<svg"))

    def test_fitted_scales_plan_into_canvas(self) -> None:
        plan = DrawPlan(
            word="kite",
            difficulty="medium",
            description="diamond shape",
            hidden_features=(),
            strokes=(
                Stroke(
                    name="outline",
                    points=(Point(30, 30), Point(50, 30), Point(50, 50), Point(30, 50), Point(30, 30)),
                ),
            ),
        )

        fitted = plan.fitted(margin=10)
        xs = [point.x for stroke in fitted.strokes for point in stroke.points]
        ys = [point.y for stroke in fitted.strokes for point in stroke.points]

        self.assertAlmostEqual(min(xs), 10.0)
        self.assertAlmostEqual(max(xs), 90.0)
        self.assertAlmostEqual(min(ys), 10.0)
        self.assertAlmostEqual(max(ys), 90.0)


if __name__ == "__main__":
    unittest.main()
