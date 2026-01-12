#!/usr/bin/env python3
"""
Final test approaches for Feb 13 detection.
Based on previous tests, the model sometimes detects Feb 13 but misidentifies its color.

New approaches:
1. Very high DPI (600) + saturation boost
2. Cropped February with color enhancement
3. Try claude-opus-4-20250514 model for better vision
4. Provide reference colors in the prompt
"""

import os
import sys
import json
import base64
import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

import anthropic
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance

PDF_PATH = PROJECT_ROOT / "Official_Calendars" / "Public" / "Butts" / "ButtsSchoolYearCalendar2025-2026_FINAL_Approved1112.pdf"


class FinalTester:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found")
        self.client = anthropic.Anthropic(api_key=api_key)

    def convert_pdf(self, dpi: int = 300) -> Image.Image:
        images = convert_from_path(str(PDF_PATH), dpi=dpi, poppler_path='/opt/homebrew/bin')
        return images[0]

    def crop_february_precise(self, img: Image.Image) -> Image.Image:
        """Crop precisely to February grid."""
        width, height = img.size
        # More precise cropping for February '26 section
        # Looking at the layout: 3 cols, 4 row groups
        # February is middle column, 3rd row group

        left = int(width * 0.34)
        right = int(width * 0.65)
        top = int(height * 0.54)
        bottom = int(height * 0.68)

        return img.crop((left, top, right, bottom))

    def image_to_bytes(self, img: Image.Image) -> bytes:
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def analyze(self, image_bytes: bytes, prompt: str, model: str = "claude-sonnet-4-20250514") -> str:
        base64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        response = self.client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64_image
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )

        return response.content[0].text

    def test_high_dpi_saturated(self):
        """Test: Very high DPI with strong saturation."""
        print("\n" + "="*60)
        print("TEST 1: Very High DPI (600) + Strong Saturation (2.5x)")
        print("="*60)

        img = self.convert_pdf(dpi=600)
        img = ImageEnhance.Color(img).enhance(2.5)

        # Save for inspection
        output_dir = PROJECT_ROOT / "scripts" / "test_images"
        output_dir.mkdir(exist_ok=True)
        img.save(output_dir / "dpi600_sat25.png")

        prompt = """Look at the February '26 section of this calendar.

The legend shows:
- Yellow background = Teacher Workday (no school for students)
- Blue background = Holiday

List EVERY date in February that has a non-white background.
For each, specify the exact color (yellow OR blue).

Check specifically:
- Feb 13 - what color is its background?
- Feb 16 - what color is its background?
- Feb 17 - what color is its background?"""

        response = self.analyze(self.image_to_bytes(img), prompt)
        print(f"\nResponse:\n{response}")

        # Check for Feb 13 with yellow
        has_feb_13_yellow = "13" in response and "yellow" in response.lower()
        return has_feb_13_yellow, response

    def test_cropped_enhanced(self):
        """Test: Cropped February with enhancement."""
        print("\n" + "="*60)
        print("TEST 2: Cropped February + Saturation + Contrast")
        print("="*60)

        img = self.convert_pdf(dpi=400)
        feb_img = self.crop_february_precise(img)

        # Enhance
        feb_img = ImageEnhance.Color(feb_img).enhance(2.0)
        feb_img = ImageEnhance.Contrast(feb_img).enhance(1.3)

        output_dir = PROJECT_ROOT / "scripts" / "test_images"
        feb_img.save(output_dir / "feb_enhanced.png")

        prompt = """This is ONLY the February portion of a school calendar.

I need you to analyze the background color of EACH date cell.
Yellow = Teacher Workday
Blue = Holiday
White = Regular school day

Looking at the dates in February:
Row 1: 1 (Sun) - 7 (Sat)
Row 2: 8 (Sun) - 14 (Sat) - CHECK Feb 13 carefully
Row 3: 15 (Sun) - 21 (Sat) - CHECK Feb 16 and 17 carefully
Row 4: 22 (Sun) - 28 (Sat)

For Feb 13, 16, and 17 specifically, what background color does each have?"""

        response = self.analyze(self.image_to_bytes(feb_img), prompt)
        print(f"\nResponse:\n{response}")

        has_feb_13_yellow = "13" in response and "yellow" in response.lower()
        return has_feb_13_yellow, response

    def test_opus_model(self):
        """Test: Use Opus model for potentially better vision."""
        print("\n" + "="*60)
        print("TEST 3: Claude Opus model (claude-opus-4-20250514)")
        print("="*60)

        img = self.convert_pdf(dpi=300)
        img = ImageEnhance.Color(img).enhance(1.5)

        prompt = """Analyze the February 2026 section of this school calendar.

According to the color legend at the bottom:
- Yellow shading = Teacher Workday (students have day off)
- Blue shading = Holiday

For EVERY date in February 2026, tell me if it has a colored background.
Pay special attention to:
- February 13 (Friday) - is it yellow, blue, or white?
- February 16 (Monday) - is it yellow, blue, or white?
- February 17 (Tuesday) - is it yellow, blue, or white?

Look at the actual shading in the calendar cells, not just text."""

        try:
            response = self.analyze(self.image_to_bytes(img), prompt, model="claude-opus-4-20250514")
            print(f"\nResponse:\n{response}")
            has_feb_13_yellow = "13" in response and "yellow" in response.lower()
            return has_feb_13_yellow, response
        except Exception as e:
            print(f"Error with Opus: {e}")
            return False, str(e)

    def test_reference_based(self):
        """Test: Provide color reference from known cells."""
        print("\n" + "="*60)
        print("TEST 4: Reference-based comparison")
        print("="*60)

        img = self.convert_pdf(dpi=400)
        img = ImageEnhance.Color(img).enhance(2.0)

        prompt = """Look at this school calendar image.

First, look at OCTOBER '25:
- Oct 6, 7, 8, 9, 10 all have YELLOW backgrounds (Teacher Workdays)
- Oct 13 has a BLUE background (Holiday)

Now look at FEBRUARY '26:
- Compare Feb 13 to Oct 6 - do they have the same YELLOW background?
- Compare Feb 16 to Oct 13 - do they have the same BLUE background?
- Compare Feb 17 to Oct 6 - do they have the same YELLOW background?

Report which February dates match the October yellow vs blue colors."""

        response = self.analyze(self.image_to_bytes(img), prompt)
        print(f"\nResponse:\n{response}")

        has_feb_13_yellow = "13" in response and ("same" in response.lower() or "yellow" in response.lower())
        return has_feb_13_yellow, response


def main():
    print("="*60)
    print("FINAL APPROACHES FOR FEB 13 DETECTION")
    print("="*60)

    tester = FinalTester()

    results = {}

    # Run tests
    results["high_dpi_saturated"], _ = tester.test_high_dpi_saturated()
    results["cropped_enhanced"], _ = tester.test_cropped_enhanced()
    results["opus_model"], _ = tester.test_opus_model()
    results["reference_based"], _ = tester.test_reference_based()

    # Summary
    print("\n" + "="*60)
    print("FINAL SUMMARY - Feb 13 with YELLOW detected?")
    print("="*60)
    for test_name, detected in results.items():
        status = "YES - DETECTED" if detected else "NO"
        print(f"  {test_name}: {status}")

    any_detected = any(results.values())
    print(f"\nAny approach detected Feb 13 as YELLOW: {any_detected}")

    # Save results
    output_file = PROJECT_ROOT / "scripts" / "final_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
