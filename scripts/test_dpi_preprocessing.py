#!/usr/bin/env python3
"""
Test different DPI and preprocessing approaches for color detection.

Tests:
1. DPI 300 vs 200
2. Different image formats (PNG vs JPEG)
3. Contrast enhancement

Target: Butts County calendar - check if Feb 13, 16, 17 are detected
"""

import os
import sys
import json
import base64
import io
from pathlib import Path
from datetime import datetime

# Add parent directory to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
except ImportError:
    pass

import anthropic
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance

# Target PDF
PDF_PATH = PROJECT_ROOT / "Official_Calendars" / "Public" / "Butts" / "ButtsSchoolYearCalendar2025-2026_FINAL_Approved1112.pdf"

# Expected February dates
EXPECTED_FEB_DATES = ["2026-02-13", "2026-02-16", "2026-02-17"]

# Simple prompt focused on February colors
FEBRUARY_PROMPT = """Look at this school calendar image and identify ALL dates in February that have ANY color/shading (not white).

For each colored date in February, report:
- The date (e.g., Feb 13)
- What color/shading you see
- Any text or label associated with it

Be extremely thorough. Look for:
- Light yellow shading
- Light blue shading
- Pink/red shading
- Gray shading
- Any background color that isn't pure white

Return your response as JSON:
{
    "february_colored_dates": [
        {"date": "Feb 13", "color": "light yellow", "label": "Teacher Workday"},
        {"date": "Feb 16", "color": "blue", "label": "Presidents Day"}
    ],
    "notes": "Any observations about the calendar colors"
}
"""


class DPIPreprocessingTester:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = anthropic.Anthropic(api_key=api_key)

    def convert_pdf_to_image(self, pdf_path: str, dpi: int = 200,
                             image_format: str = "PNG",
                             contrast_factor: float = None) -> bytes:
        """Convert PDF to image with specified parameters."""
        images = convert_from_path(pdf_path, dpi=dpi, poppler_path='/opt/homebrew/bin')

        if not images:
            raise ValueError("No images extracted from PDF")

        # Use first page
        img = images[0]

        # Apply contrast enhancement if specified
        if contrast_factor and contrast_factor != 1.0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(contrast_factor)

        # Convert to specified format
        buffer = io.BytesIO()
        if image_format.upper() == "JPEG":
            # Convert RGBA to RGB for JPEG
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.save(buffer, format='JPEG', quality=95)
        else:
            img.save(buffer, format='PNG')

        return buffer.getvalue()

    def analyze_image(self, image_bytes: bytes, media_type: str = "image/png") -> dict:
        """Send image to Claude and ask about February colors."""
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
                            "media_type": media_type,
                            "data": base64_image
                        }
                    },
                    {
                        "type": "text",
                        "text": FEBRUARY_PROMPT
                    }
                ]
            }]
        )

        response_text = response.content[0].text

        # Try to extract JSON
        try:
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

        return {"raw_response": response_text}

    def check_feb_dates(self, result: dict) -> dict:
        """Check if Feb 13, 16, 17 were detected."""
        colored_dates = result.get("february_colored_dates", [])

        detected = {
            "feb_13": False,
            "feb_16": False,
            "feb_17": False
        }

        for entry in colored_dates:
            date_str = entry.get("date", "").lower()
            if "13" in date_str:
                detected["feb_13"] = True
            if "16" in date_str:
                detected["feb_16"] = True
            if "17" in date_str:
                detected["feb_17"] = True

        detected["all_detected"] = all(detected.values())
        detected["raw_dates"] = [d.get("date") for d in colored_dates]

        return detected

    def run_test(self, test_name: str, dpi: int, image_format: str,
                 contrast_factor: float = None) -> dict:
        """Run a single test configuration."""
        print(f"\n{'='*60}")
        print(f"TEST: {test_name}")
        print(f"  DPI: {dpi}, Format: {image_format}, Contrast: {contrast_factor or 'None'}")
        print("="*60)

        try:
            # Convert PDF
            print("  Converting PDF to image...")
            media_type = "image/jpeg" if image_format.upper() == "JPEG" else "image/png"
            image_bytes = self.convert_pdf_to_image(
                str(PDF_PATH),
                dpi=dpi,
                image_format=image_format,
                contrast_factor=contrast_factor
            )
            print(f"  Image size: {len(image_bytes):,} bytes")

            # Analyze with Claude
            print("  Sending to Claude API...")
            result = self.analyze_image(image_bytes, media_type)

            # Check for target dates
            detection = self.check_feb_dates(result)

            print(f"\n  Results:")
            print(f"    Feb 13 detected: {detection['feb_13']}")
            print(f"    Feb 16 detected: {detection['feb_16']}")
            print(f"    Feb 17 detected: {detection['feb_17']}")
            print(f"    All dates found: {detection['all_detected']}")
            print(f"    Raw dates: {detection['raw_dates']}")

            if result.get("notes"):
                print(f"    Notes: {result.get('notes')}")

            return {
                "test_name": test_name,
                "dpi": dpi,
                "format": image_format,
                "contrast": contrast_factor,
                "image_size_bytes": len(image_bytes),
                "detection": detection,
                "raw_result": result
            }

        except Exception as e:
            print(f"  ERROR: {e}")
            return {
                "test_name": test_name,
                "error": str(e)
            }


def main():
    print("="*60)
    print("DPI AND PREPROCESSING TEST FOR BUTTS COUNTY CALENDAR")
    print(f"Target file: {PDF_PATH}")
    print(f"Looking for: Feb 13, 16, 17 colored dates")
    print("="*60)

    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}")
        return

    tester = DPIPreprocessingTester()

    # Define test configurations
    tests = [
        # Test 1: Baseline - DPI 200, PNG, no contrast
        ("Baseline (DPI 200, PNG)", 200, "PNG", None),

        # Test 2: Higher DPI
        ("Higher DPI (300, PNG)", 300, "PNG", None),

        # Test 3: JPEG format
        ("JPEG format (DPI 200)", 200, "JPEG", None),

        # Test 4: JPEG with higher DPI
        ("JPEG + Higher DPI (300)", 300, "JPEG", None),

        # Test 5: Increased contrast (1.3x)
        ("Contrast 1.3x (DPI 200, PNG)", 200, "PNG", 1.3),

        # Test 6: Higher contrast (1.5x)
        ("Contrast 1.5x (DPI 200, PNG)", 200, "PNG", 1.5),

        # Test 7: Contrast + Higher DPI
        ("Contrast 1.3x + DPI 300", 300, "PNG", 1.3),
    ]

    results = []
    for test_name, dpi, fmt, contrast in tests:
        result = tester.run_test(test_name, dpi, fmt, contrast)
        results.append(result)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"{'Test Name':<35} {'Feb 13':<10} {'Feb 16':<10} {'Feb 17':<10} {'All?':<6}")
    print("-"*71)

    for r in results:
        if "error" in r:
            print(f"{r['test_name']:<35} ERROR: {r['error']}")
        else:
            d = r["detection"]
            print(f"{r['test_name']:<35} {str(d['feb_13']):<10} {str(d['feb_16']):<10} {str(d['feb_17']):<10} {str(d['all_detected']):<6}")

    # Identify best approach
    print("\n" + "="*60)
    print("ANALYSIS")
    print("="*60)

    feb_13_detected = [r for r in results if "error" not in r and r["detection"]["feb_13"]]
    all_detected = [r for r in results if "error" not in r and r["detection"]["all_detected"]]

    if feb_13_detected:
        print(f"\nApproaches that detected Feb 13:")
        for r in feb_13_detected:
            print(f"  - {r['test_name']}")
    else:
        print("\nNO approach detected Feb 13!")

    if all_detected:
        print(f"\nApproaches that detected ALL dates (13, 16, 17):")
        for r in all_detected:
            print(f"  - {r['test_name']}")

    # Save detailed results
    output_file = PROJECT_ROOT / "scripts" / "dpi_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
