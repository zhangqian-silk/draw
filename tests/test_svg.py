import unittest

from drawbot.svg import SvgParseError, extract_svg_fragment, parse_svg_document


class SvgTests(unittest.TestCase):
    def test_extract_svg_fragment_from_code_fence(self) -> None:
        fragment = extract_svg_fragment(
            """
            ```svg
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>
            ```
            """
        )

        self.assertTrue(fragment.startswith("<svg"))

    def test_parse_svg_document_ignores_white_background_rect(self) -> None:
        strokes, title, description = parse_svg_document(
            """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
              <title>house</title>
              <desc>simple house outline</desc>
              <rect x="0" y="0" width="100" height="100" fill="white" stroke="none" />
              <path d="M20 60 L50 30 L80 60" stroke="black" fill="none" />
              <rect x="28" y="60" width="44" height="24" stroke="black" fill="none" />
            </svg>
            """
        )

        self.assertEqual(title, "house")
        self.assertEqual(description, "simple house outline")
        self.assertEqual(len(strokes), 2)

    def test_parse_svg_document_supports_circle(self) -> None:
        strokes, _, _ = parse_svg_document(
            """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="20" stroke="black" fill="none" />
            </svg>
            """
        )

        self.assertEqual(len(strokes), 1)
        self.assertGreater(len(strokes[0].points), 10)

    def test_parse_svg_document_rejects_transform(self) -> None:
        with self.assertRaises(SvgParseError):
            parse_svg_document(
                """
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
                  <path d="M10 10 L90 90" stroke="black" fill="none" transform="scale(0.8)" />
                </svg>
                """
            )


if __name__ == "__main__":
    unittest.main()
