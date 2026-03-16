import unittest

from drawbot.mouse import MouseButton


class MouseButtonTests(unittest.TestCase):
    def test_parse_left_and_right(self) -> None:
        self.assertEqual(MouseButton.parse("left"), MouseButton.LEFT)
        self.assertEqual(MouseButton.parse("RIGHT"), MouseButton.RIGHT)

    def test_parse_rejects_unknown_button(self) -> None:
        with self.assertRaises(ValueError):
            MouseButton.parse("middle")


if __name__ == "__main__":
    unittest.main()
