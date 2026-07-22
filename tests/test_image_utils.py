import io
import random
import unittest

from PIL import Image, ImageDraw

from renderers.image_utils import encode_png_limited


class ImageUtilsTests(unittest.TestCase):
    def test_encode_png_limited_caps_dimensions_and_bytes(self):
        image = Image.new("RGB", (1500, 2400), (18, 24, 39))
        draw = ImageDraw.Draw(image)
        for y in range(0, image.height, 12):
            draw.line((0, y, image.width, y), fill=(y % 255, 120, 180), width=2)

        encoded = encode_png_limited(
            image,
            max_bytes=180_000,
            max_width=1080,
            max_height=1800,
        )

        self.assertLessEqual(len(encoded), 180_000)
        rendered = Image.open(io.BytesIO(encoded))
        self.assertLessEqual(rendered.width, 1080)
        self.assertLessEqual(rendered.height, 1800)

    def test_encode_png_limited_enforces_byte_ceiling_for_noisy_input(self):
        random_bytes = random.Random(7).randbytes(800 * 1200 * 3)
        image = Image.frombytes("RGB", (800, 1200), random_bytes)

        encoded = encode_png_limited(image, max_bytes=150_000)

        self.assertLessEqual(len(encoded), 150_000)
        rendered = Image.open(io.BytesIO(encoded))
        self.assertGreaterEqual(rendered.width, 360)
        self.assertGreaterEqual(rendered.height, 420)


if __name__ == "__main__":
    unittest.main()
