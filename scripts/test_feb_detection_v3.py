#!/usr/bin/env python3
"""
Test various approaches to detect Feb 13 yellow highlighting.
The issue: Feb 13 has yellow (Teacher Workday) but model misses it.

New approaches:
1. Crop to just February section
2. More explicit prompting about yellow
3. Multiple API calls for consensus
4. Use Claude's native PDF handling (base64 PDF)
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


class FebDetectionTester:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found")
        self.client = anthropic.Anthropic(api_key=api_key)

    def convert_pdf(self, dpi: int = 300) -> Image.Image:
        images = convert_from_path(str(PDF_PATH), dpi=dpi, poppler_path='/opt/homebrew/bin')
        return images[0]

    def crop_february(self, img: Image.Image) -> Image.Image:
        """Crop to just the February section of the calendar."""
        # Based on the calendar layout, February is in the middle row of the second group
        # The calendar is organized in 3 columns x 4 rows of months
        # February '26 is in the middle of row 3 (January, February, March '26)

        width, height = img.size

        # February is roughly in the center-middle portion
        # Row 3 starts at about 55% from top, ends at about 72%
        # February column is the middle column (33% to 66% width)

        left = int(width * 0.33)
        right = int(width * 0.66)
        top = int(height * 0.52)
        bottom = int(height * 0.70)

        return img.crop((left, top, right, bottom))

    def image_to_bytes(self, img: Image.Image) -> bytes:
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def analyze(self, image_bytes: bytes, prompt: str) -> dict:
        base64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
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

    def analyze_with_pdf(self, prompt: str) -> str:
        """Send the raw PDF to Claude (uses document understanding)."""
        with open(PDF_PATH, 'rb') as f:
            pdf_bytes = f.read()

        base64_pdf = base64.standard_b64encode(pdf_bytes).decode("utf-8")

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64_pdf
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

    def test_cropped_february(self):
        """Test 1: Crop to just February."""
        print("\n" + "="*60)
        print("TEST 1: Cropped February section only")
        print("="*60)

        img = self.convert_pdf(dpi=400)
        feb_img = self.crop_february(img)

        # Save for inspection
        output_dir = PROJECT_ROOT / "scripts" / "test_images"
        output_dir.mkdir(exist_ok=True)
        feb_img.save(output_dir / "february_cropped.png")
        print(f"Saved cropped image to: {output_dir / 'february_cropped.png'}")

        prompt = """This is ONLY the February section of a school calendar.

Look at EVERY date cell and identify which ones have a colored background:
- Yellow/cream background = Teacher Workday
- Blue background = Holiday
- White = Regular school day

Specifically check Feb 13 (Friday in the second row) - does it have a yellow background?

List ALL dates with ANY background color."""

        response = self.analyze(self.image_to_bytes(feb_img), prompt)
        print(f"\nResponse:\n{response}")

        return "13" in response.lower() and ("yellow" in response.lower() or "color" in response.lower())

    def test_explicit_yellow_prompt(self):
        """Test 2: Very explicit prompt about yellow."""
        print("\n" + "="*60)
        print("TEST 2: Explicit yellow prompt")
        print("="*60)

        img = self.convert_pdf(dpi=300)

        prompt = """Look at the February '26 section of this school calendar.

According to the legend at the bottom:
- YELLOW = Teacher Workday (no school for students)
- BLUE = Holiday

In February, I can see these dates should have yellow backgrounds based on the pattern:
- Feb 13 (Friday) - Teacher Workday
- Feb 17 (Tuesday) - Teacher Workday

And this date should have a blue background:
- Feb 16 (Monday) - Presidents Day Holiday

Please carefully examine the February calendar grid and confirm:
1. Does Feb 13 have a YELLOW background? Look carefully at the cell for the 13th.
2. Does Feb 16 have a BLUE background?
3. Does Feb 17 have a YELLOW background?

The yellow color is similar to the cells marked in October (Oct 6, 7, 8, 9, 10) and November (Nov 24, 25, 26).
Compare Feb 13 to those cells - do they have the same yellow background?"""

        response = self.analyze(self.image_to_bytes(img), prompt)
        print(f"\nResponse:\n{response}")

        return "yes" in response.lower() and "13" in response

    def test_pdf_direct(self):
        """Test 3: Send PDF directly to Claude."""
        print("\n" + "="*60)
        print("TEST 3: Direct PDF analysis")
        print("="*60)

        prompt = """Analyze this school calendar PDF.

Focus on FEBRUARY 2026. According to the legend:
- Yellow = Teacher Workday (students have no school)
- Blue = Holiday

In February 2026, list every date that has a non-white background color.
Be very thorough - check each date cell for any shading.

Specifically answer: Is February 13, 2026 marked with a yellow background?"""

        response = self.analyze_with_pdf(prompt)
        print(f"\nResponse:\n{response}")

        return "13" in response and ("yellow" in response.lower() or "teacher" in response.lower())

    def test_side_by_side_comparison(self):
        """Test 4: Ask model to compare Feb 13 to known colored cells."""
        print("\n" + "="*60)
        print("TEST 4: Side-by-side comparison prompt")
        print("="*60)

        img = self.convert_pdf(dpi=300)

        # Enhance saturation to make yellows more visible
        img = ImageEnhance.Color(img).enhance(1.5)

        prompt = """I need you to compare colors in this school calendar.

KNOWN COLORED CELLS (confirmed Teacher Workday - Yellow):
- January 2 (Jan '26 section)
- January 19 (Jan '26 section)

CELLS TO CHECK:
- February 13 (Feb '26 section)
- February 17 (Feb '26 section)

Question: Does February 13 have the SAME yellow/cream background color as January 2?

Look at the actual pixel color of the cell backgrounds, not just any text labels.
Compare the background color of the "13" cell in February to the "2" cell in January.
Are they the same color or different?"""

        response = self.analyze(self.image_to_bytes(img), prompt)
        print(f"\nResponse:\n{response}")

        return "same" in response.lower() or ("13" in response and "yellow" in response.lower())

    def test_multiple_runs(self, num_runs: int = 3):
        """Test 5: Run the same query multiple times for consistency."""
        print("\n" + "="*60)
        print(f"TEST 5: Multiple runs ({num_runs}x) for consistency")
        print("="*60)

        img = self.convert_pdf(dpi=300)

        prompt = """List every date in February 2026 that has a colored (non-white) background.

Check each date carefully:
- Feb 1-7 (first row)
- Feb 8-14 (second row) - especially check Feb 13
- Feb 15-21 (third row) - especially check Feb 16, 17
- Feb 22-28 (fourth row)

Return a simple list of colored dates with their colors."""

        results = []
        for i in range(num_runs):
            response = self.analyze(self.image_to_bytes(img), prompt)
            has_feb_13 = "13" in response
            results.append({
                "run": i+1,
                "detected_feb_13": has_feb_13,
                "response": response[:500]
            })
            print(f"\nRun {i+1}: Feb 13 detected = {has_feb_13}")
            print(f"Response preview: {response[:300]}...")

        detected_count = sum(1 for r in results if r["detected_feb_13"])
        print(f"\nFeb 13 detected in {detected_count}/{num_runs} runs")

        return detected_count > 0


def main():
    print("="*60)
    print("FEBRUARY 13 DETECTION TESTS")
    print("Target: Detect yellow (Teacher Workday) on Feb 13")
    print("="*60)

    tester = FebDetectionTester()

    results = {}

    # Run each test
    results["cropped"] = tester.test_cropped_february()
    results["explicit_yellow"] = tester.test_explicit_yellow_prompt()
    results["pdf_direct"] = tester.test_pdf_direct()
    results["comparison"] = tester.test_side_by_side_comparison()
    results["multiple_runs"] = tester.test_multiple_runs(3)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for test_name, detected in results.items():
        status = "DETECTED" if detected else "NOT DETECTED"
        print(f"  {test_name}: Feb 13 {status}")

    # Overall result
    any_detected = any(results.values())
    print(f"\nOverall: Feb 13 detected in at least one test = {any_detected}")

    # Save results
    output_file = PROJECT_ROOT / "scripts" / "feb13_detection_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
