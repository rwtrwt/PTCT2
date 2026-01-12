#!/usr/bin/env python3
"""
Test additional preprocessing approaches for color detection.
Version 2 - More aggressive approaches

Tests:
1. Saturation enhancement
2. Color space conversion (HSV)
3. Very high contrast
4. Explicit prompting about Feb 13
5. Save test images for visual inspection
"""

import os
import sys
import json
import base64
import io
from pathlib import Path

# Add parent directory to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file
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
import cv2
import numpy as np

# Target PDF
PDF_PATH = PROJECT_ROOT / "Official_Calendars" / "Public" / "Butts" / "ButtsSchoolYearCalendar2025-2026_FINAL_Approved1112.pdf"

# More specific prompt
FOCUSED_PROMPT = """Look at this school calendar image. Focus specifically on FEBRUARY.

CRITICAL: Look very carefully at Feb 13 (Friday). Check if it has ANY shading or color - even very light/subtle coloring like pale yellow, cream, or light gray.

For EVERY date from Feb 1 through Feb 28, tell me:
- Does it have ANY background color (even very faint)?
- What color is it?

Common colors in school calendars:
- Light yellow/cream = Teacher Workday
- Blue = Holiday
- Pink/Red = No School
- White = Regular school day

Return JSON:
{
    "february_analysis": {
        "feb_13": {"has_color": true/false, "color_description": "...", "confidence": 0-100},
        "feb_16": {"has_color": true/false, "color_description": "...", "confidence": 0-100},
        "feb_17": {"has_color": true/false, "color_description": "...", "confidence": 0-100}
    },
    "all_colored_dates_in_february": ["Feb X", "Feb Y", ...],
    "notes": "..."
}
"""


class AdvancedTester:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found")
        self.client = anthropic.Anthropic(api_key=api_key)

    def pil_to_cv2(self, pil_img):
        """Convert PIL image to OpenCV format."""
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def cv2_to_pil(self, cv2_img):
        """Convert OpenCV image to PIL format."""
        return Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))

    def enhance_saturation(self, img: Image.Image, factor: float) -> Image.Image:
        """Enhance color saturation."""
        enhancer = ImageEnhance.Color(img)
        return enhancer.enhance(factor)

    def enhance_sharpness(self, img: Image.Image, factor: float) -> Image.Image:
        """Enhance sharpness."""
        enhancer = ImageEnhance.Sharpness(img)
        return enhancer.enhance(factor)

    def enhance_brightness(self, img: Image.Image, factor: float) -> Image.Image:
        """Enhance brightness."""
        enhancer = ImageEnhance.Brightness(img)
        return enhancer.enhance(factor)

    def apply_clahe(self, img: Image.Image) -> Image.Image:
        """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)."""
        cv2_img = self.pil_to_cv2(img)
        lab = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        lab = cv2.merge([l, a, b])
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return self.cv2_to_pil(result)

    def convert_pdf(self, dpi: int = 200) -> Image.Image:
        """Convert PDF to image."""
        images = convert_from_path(str(PDF_PATH), dpi=dpi, poppler_path='/opt/homebrew/bin')
        return images[0] if images else None

    def save_image(self, img: Image.Image, name: str) -> str:
        """Save image for inspection."""
        output_dir = PROJECT_ROOT / "scripts" / "test_images"
        output_dir.mkdir(exist_ok=True)
        path = output_dir / f"{name}.png"
        img.save(path)
        return str(path)

    def image_to_bytes(self, img: Image.Image, format: str = "PNG") -> bytes:
        """Convert image to bytes."""
        buffer = io.BytesIO()
        img.save(buffer, format=format)
        return buffer.getvalue()

    def analyze_image(self, image_bytes: bytes, prompt: str) -> dict:
        """Send image to Claude."""
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

        response_text = response.content[0].text

        try:
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

        return {"raw_response": response_text}

    def check_detection(self, result: dict) -> dict:
        """Check if Feb 13, 16, 17 detected."""
        # Check the new analysis format
        feb_analysis = result.get("february_analysis", {})
        all_colored = result.get("all_colored_dates_in_february", [])

        detected = {
            "feb_13": False,
            "feb_16": False,
            "feb_17": False
        }

        # Check from february_analysis
        if feb_analysis.get("feb_13", {}).get("has_color"):
            detected["feb_13"] = True
        if feb_analysis.get("feb_16", {}).get("has_color"):
            detected["feb_16"] = True
        if feb_analysis.get("feb_17", {}).get("has_color"):
            detected["feb_17"] = True

        # Also check from all_colored_dates_in_february
        for date_str in all_colored:
            date_str = str(date_str).lower()
            if "13" in date_str:
                detected["feb_13"] = True
            if "16" in date_str:
                detected["feb_16"] = True
            if "17" in date_str:
                detected["feb_17"] = True

        detected["all_detected"] = all(detected.values())
        detected["feb_analysis"] = feb_analysis
        detected["all_colored"] = all_colored

        return detected

    def run_test(self, name: str, img: Image.Image, prompt: str = FOCUSED_PROMPT) -> dict:
        """Run a single test."""
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print("="*60)

        try:
            # Save image for inspection
            saved_path = self.save_image(img, name.replace(" ", "_").replace("(", "").replace(")", "").replace("+", "_"))
            print(f"  Saved to: {saved_path}")

            # Convert and analyze
            image_bytes = self.image_to_bytes(img)
            print(f"  Image size: {len(image_bytes):,} bytes")
            print("  Analyzing with Claude...")

            result = self.analyze_image(image_bytes, prompt)
            detection = self.check_detection(result)

            print(f"\n  Results:")
            print(f"    Feb 13 detected: {detection['feb_13']}")
            print(f"    Feb 16 detected: {detection['feb_16']}")
            print(f"    Feb 17 detected: {detection['feb_17']}")
            if detection.get("feb_analysis", {}).get("feb_13"):
                print(f"    Feb 13 analysis: {detection['feb_analysis']['feb_13']}")
            print(f"    All colored dates: {detection.get('all_colored', [])}")

            return {
                "test_name": name,
                "detection": detection,
                "raw_result": result
            }

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            return {"test_name": name, "error": str(e)}


def main():
    print("="*60)
    print("ADVANCED PREPROCESSING TESTS V2")
    print("="*60)

    tester = AdvancedTester()

    # Get base image at high DPI
    print("\nLoading PDF at DPI 300...")
    base_img = tester.convert_pdf(dpi=300)

    results = []

    # Test 1: High saturation enhancement
    print("\nTest 1: High saturation enhancement (2.0x)")
    img1 = tester.enhance_saturation(base_img, 2.0)
    results.append(tester.run_test("Saturation_2x", img1))

    # Test 2: Very high saturation
    print("\nTest 2: Very high saturation (3.0x)")
    img2 = tester.enhance_saturation(base_img, 3.0)
    results.append(tester.run_test("Saturation_3x", img2))

    # Test 3: CLAHE
    print("\nTest 3: CLAHE enhancement")
    img3 = tester.apply_clahe(base_img)
    results.append(tester.run_test("CLAHE", img3))

    # Test 4: Combined saturation + contrast
    print("\nTest 4: Saturation 2x + Contrast 1.5x")
    img4 = tester.enhance_saturation(base_img, 2.0)
    img4 = ImageEnhance.Contrast(img4).enhance(1.5)
    results.append(tester.run_test("Saturation_Contrast", img4))

    # Test 5: Sharpness + saturation
    print("\nTest 5: Sharpness 2x + Saturation 2x")
    img5 = tester.enhance_sharpness(base_img, 2.0)
    img5 = tester.enhance_saturation(img5, 2.0)
    results.append(tester.run_test("Sharp_Saturated", img5))

    # Test 6: Very high DPI (400)
    print("\nTest 6: Very high DPI (400)")
    img6 = tester.convert_pdf(dpi=400)
    results.append(tester.run_test("DPI_400", img6))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    for r in results:
        if "error" in r:
            print(f"{r['test_name']}: ERROR")
        else:
            d = r["detection"]
            print(f"{r['test_name']}: Feb13={d['feb_13']}, Feb16={d['feb_16']}, Feb17={d['feb_17']}")

    # Save results
    output_file = PROJECT_ROOT / "scripts" / "dpi_test_results_v2.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
