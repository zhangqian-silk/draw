import unittest
from unittest.mock import patch

from drawbot.models import Region
from drawbot.planner import DEFAULT_OPENAI_MODEL, OpenAIPlanner


class OpenAIPlannerTests(unittest.TestCase):
    def test_defaults_model(self) -> None:
        planner = OpenAIPlanner()
        self.assertEqual(planner.model, DEFAULT_OPENAI_MODEL)

    def test_build_user_prompt_includes_region_shape(self) -> None:
        planner = OpenAIPlanner(model="example-model")
        prompt = planner.build_user_prompt(
            prompt="draw a bicycle from the side",
            difficulty="medium",
            style="silhouette",
            drawing_mode="precise",
            pictionary_strategy="scene",
            region=Region(left=0, top=0, width=640, height=320),
            extra_instruction="focus on the wheels first",
        )

        self.assertIn("draw a bicycle from the side", prompt)
        self.assertIn("aspect ratio 2.00", prompt)
        self.assertIn("focus on the wheels first", prompt)
        self.assertIn("Draw the literal target itself as faithfully as possible", prompt)

    def test_build_user_prompt_includes_pictionary_guidance(self) -> None:
        planner = OpenAIPlanner(model="example-model")
        prompt = planner.build_user_prompt(
            prompt="draw thunder",
            difficulty="medium",
            style="gesture",
            drawing_mode="pictionary",
            pictionary_strategy="symbol",
            region=None,
            extra_instruction="avoid the literal word",
        )

        self.assertIn("Drawing mode: pictionary.", prompt)
        self.assertIn("Use associative visual clues instead of directly drawing the target", prompt)
        self.assertIn("association, not from leaving the drawing incomplete", prompt)
        self.assertIn("Prefer symbolic, metaphorical, or iconic clues", prompt)

    def test_plan_keeps_full_shape_when_reveal_ratio_is_not_provided(self) -> None:
        planner = OpenAIPlanner(model="example-model")

        class FakeResponses:
            call_count = 0

            @staticmethod
            def create(**_kwargs):
                FakeResponses.call_count += 1
                if FakeResponses.call_count == 1:
                    return type(
                        "Response",
                        (),
                        {
                            "output_text": (
                                '{"subject":"house","viewpoint":"front","pose":"still","composition":"centered",'
                                '"silhouette":"simple square house with roof","anchor_features":["roof","walls","door"],'
                                '"stroke_intent":["roof outline","wall outline","door detail"],"avoid":["random curves"]}'
                            )
                        },
                    )()
                if FakeResponses.call_count == 2:
                    output_text = """
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
                      <rect x="0" y="0" width="100" height="100" fill="white" stroke="none" />
                      <path d="M20 55 L50 28 L80 55" stroke="black" fill="none" />
                      <rect x="28" y="55" width="44" height="24" stroke="black" fill="none" />
                    </svg>
                    """
                else:
                    output_text = """
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
                      <rect x="0" y="0" width="100" height="100" fill="white" stroke="none" />
                      <path d="M18 56 L50 25 L82 56" stroke="black" fill="none" />
                      <rect x="26" y="56" width="48" height="24" stroke="black" fill="none" />
                      <line x1="46" y1="64" x2="46" y2="80" stroke="black" />
                    </svg>
                    """
                return type(
                    "Response",
                    (),
                    {"output_text": output_text},
                )()

        fake_client = type("FakeClient", (), {"responses": FakeResponses()})()

        with patch.object(planner, "_build_client", return_value=fake_client):
            plan = planner.plan(prompt="draw a house", difficulty="medium")

        self.assertTrue(plan.svg.strip().startswith("<svg"))
        self.assertGreaterEqual(len(plan.strokes), 2)


if __name__ == "__main__":
    unittest.main()
