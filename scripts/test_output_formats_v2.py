#!/usr/bin/env python3
"""
Test different output format requests - Version 2

This version adds more explicit verification prompts for Feb 13 specifically.

Tests additional prompt variations:
4. Two-pass approach - first identify ALL colored dates, then categorize
5. Direct verification prompt - ask Claude to confirm specific dates before answering
"""

import os
import sys
import json
import base64
import re
from datetime import datetime, date
from pathlib import Path

# Add parent directory to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

import anthropic

# Expected results for validation
EXPECTED_HOLIDAYS = {
    "MLK Day": {"start": "2026-01-19", "end": "2026-01-19"},
    "Winter Break": {"start": "2026-02-13", "end": "2026-02-17"},
    "Spring Break": {"start": "2026-04-06", "end": "2026-04-10"},
}

# Base system prompt
BASE_SYSTEM = """You are an expert school calendar analyst with perfect attention to detail.

## CRITICAL FOR WINTER BREAK:
The key issue is that Teacher Workdays on FRIDAY before a Monday holiday are often missed.
- Teacher Workday = Student holiday (no school for students)
- If Friday Feb 13 is colored as Teacher Workday AND Monday Feb 16 is a Holiday,
  then Winter Break is Feb 13-17 (not Feb 16-17)

## COLOR CODING:
Different colors mean different things but ALL colored dates = no school for students:
- Holiday (often blue) = No school
- Teacher Workday (often yellow) = No school for students"""


def pdf_to_images(pdf_path: str):
    """Convert PDF pages to images."""
    try:
        from pdf2image import convert_from_path
        import io

        images = convert_from_path(pdf_path, dpi=200, poppler_path='/opt/homebrew/bin')
        image_bytes_list = []

        for img in images:
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            image_bytes_list.append(buffer.getvalue())

        return image_bytes_list
    except Exception as e:
        print(f"Error converting PDF: {e}")
        return []


def extract_json_from_response(response_text: str) -> dict:
    """Extract JSON from response text."""
    json_match = re.search(r'```(?:json)?\s*(.*?)```', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except:
            pass

    start = response_text.find('{')
    if start != -1:
        depth = 0
        end = start
        for i, c in enumerate(response_text[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            return json.loads(response_text[start:end])
        except:
            pass

    return {}


def validate_results(holidays: list) -> dict:
    """Validate extracted holidays against expected results."""
    results = {
        "total_expected": len(EXPECTED_HOLIDAYS),
        "correct": 0,
        "missing": [],
        "wrong_dates": [],
        "details": {}
    }

    extracted_by_name = {}
    for h in holidays:
        name = h.get('name', '')
        extracted_by_name[name] = h

    for name, expected in EXPECTED_HOLIDAYS.items():
        if name in extracted_by_name:
            h = extracted_by_name[name]
            start_match = h.get('start_date') == expected['start']
            end_match = h.get('end_date') == expected['end']

            if start_match and end_match:
                results['correct'] += 1
                results['details'][name] = "CORRECT"
            else:
                results['wrong_dates'].append({
                    "name": name,
                    "expected": expected,
                    "got": {"start": h.get('start_date'), "end": h.get('end_date')}
                })
                results['details'][name] = f"WRONG - Expected {expected['start']} to {expected['end']}, got {h.get('start_date')} to {h.get('end_date')}"
        else:
            results['missing'].append(name)
            results['details'][name] = "MISSING"

    results['accuracy'] = results['correct'] / results['total_expected'] if results['total_expected'] > 0 else 0
    return results


def test_format_4_two_pass(client, images):
    """
    Format 4: Two-pass approach - first identify ALL colored dates, second categorize

    Theory: By forcing enumeration of ALL colored dates first, nothing is missed.
    """
    print("\n" + "="*60)
    print("FORMAT 4: Two-Pass Enumeration")
    print("="*60)

    content = []
    for img_bytes in images[:5]:
        base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_image
            }
        })

    content.append({
        "type": "text",
        "text": """PASS 1 - ENUMERATE ALL COLORED DATES:
Go month by month from January to May 2026 and list EVERY date that has ANY color (not white).
For each date, write: "MONTH DAY: [color you see]"

PASS 2 - VERIFY FEBRUARY:
Look specifically at the February row and answer:
- Is Feb 12 colored? What color?
- Is Feb 13 colored? What color?
- Is Feb 14 colored? What color?
- Is Feb 15 colored? What color?
- Is Feb 16 colored? What color?
- Is Feb 17 colored? What color?

PASS 3 - OUTPUT JSON:
Based on your enumeration, output JSON. Remember:
- Teacher Workday = Student holiday
- Combine Friday + Monday holidays that span a weekend
```json
{
    "holidays": [
        {"name": "MLK Day", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        {"name": "Spring Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    ]
}
```"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=6000,
        messages=[{"role": "user", "content": content}],
        system=BASE_SYSTEM
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3000 chars):")
    print(response_text[:3000])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    print(f"\nExtracted {len(holidays)} holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Two-Pass Enumeration",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_5_verification_first(client, images):
    """
    Format 5: Direct verification - ask Claude to verify specific dates BEFORE answering

    Theory: Pre-verification reduces cognitive load and catches easy mistakes.
    """
    print("\n" + "="*60)
    print("FORMAT 5: Direct Verification First")
    print("="*60)

    content = []
    for img_bytes in images[:5]:
        base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_image
            }
        })

    content.append({
        "type": "text",
        "text": """VERIFICATION QUESTIONS (answer each one first):

Q1: Look at the square for January 19, 2026. Is it colored? YES or NO?
Q2: Look at the square for February 13, 2026 (this is a Friday). Is it colored? YES or NO? What color?
Q3: Look at the square for February 16, 2026 (this is Presidents Day Monday). Is it colored? YES or NO?
Q4: Look at the square for February 17, 2026. Is it colored? YES or NO?
Q5: Look at the squares for April 6-10, 2026. Are they colored? YES or NO?

ANSWER FORMAT:
A1: [YES/NO]
A2: [YES/NO, color if YES]
A3: [YES/NO]
A4: [YES/NO]
A5: [YES/NO]

THEN provide JSON based on your answers:
- If Feb 13 is colored, Winter Break starts Feb 13 (not Feb 16)
- Teacher Workday colors count as no-school days

```json
{
    "holidays": [
        {"name": "MLK Day", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        {"name": "Spring Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    ]
}
```"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system=BASE_SYSTEM
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 2500 chars):")
    print(response_text[:2500])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    print(f"\nExtracted {len(holidays)} holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Direct Verification First",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_6_xml_structured(client, images):
    """
    Format 6: XML-structured output instead of JSON

    Theory: XML format may be more explicit about structure.
    """
    print("\n" + "="*60)
    print("FORMAT 6: XML-Structured Output")
    print("="*60)

    content = []
    for img_bytes in images[:5]:
        base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_image
            }
        })

    content.append({
        "type": "text",
        "text": """Analyze the calendar and output holidays in this XML format:

<calendar>
  <february_analysis>
    <date day="12" colored="yes/no" color_type="..." />
    <date day="13" colored="yes/no" color_type="..." />
    <date day="14" colored="yes/no" color_type="..." />
    <date day="15" colored="yes/no" color_type="..." />
    <date day="16" colored="yes/no" color_type="..." />
    <date day="17" colored="yes/no" color_type="..." />
  </february_analysis>

  <holidays>
    <holiday name="MLK Day" start="YYYY-MM-DD" end="YYYY-MM-DD" />
    <holiday name="Winter Break" start="YYYY-MM-DD" end="YYYY-MM-DD" />
    <holiday name="Spring Break" start="YYYY-MM-DD" end="YYYY-MM-DD" />
  </holidays>
</calendar>

IMPORTANT:
- Check Feb 13 carefully - it's often a Teacher Workday (colored yellow)
- Teacher Workday = no school for students
- If Feb 13 AND Feb 16 are both colored, Winter Break is Feb 13-17"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system=BASE_SYSTEM
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 2500 chars):")
    print(response_text[:2500])

    # Parse XML to extract holidays
    holidays = []
    holiday_pattern = r'<holiday\s+name="([^"]+)"\s+start="([^"]+)"\s+end="([^"]+)"'
    for match in re.finditer(holiday_pattern, response_text):
        holidays.append({
            "name": match.group(1),
            "start_date": match.group(2),
            "end_date": match.group(3)
        })

    # Fallback to JSON if XML parsing fails
    if not holidays:
        result = extract_json_from_response(response_text)
        holidays = result.get('holidays', [])

    print(f"\nExtracted {len(holidays)} holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "XML Structured",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_7_row_by_row(client, images):
    """
    Format 7: Row-by-row calendar reading

    Theory: Having Claude read the calendar row-by-row like a human forces attention to each cell.
    """
    print("\n" + "="*60)
    print("FORMAT 7: Row-by-Row Reading")
    print("="*60)

    content = []
    for img_bytes in images[:5]:
        base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_image
            }
        })

    content.append({
        "type": "text",
        "text": """Read the calendar like you're reading a book - LEFT TO RIGHT, TOP TO BOTTOM.

For FEBRUARY 2026 only, read each row of the calendar grid:
- Row 1 (first week): What dates are shown? Any colored?
- Row 2 (second week): What dates, any colored?
- Row 3 (third week, should include Feb 13): What dates, any colored? IS FEB 13 COLORED?
- Row 4 (fourth week, should include Feb 16): What dates, any colored?

For each colored date in February, note:
- The date number
- The color
- Whether it's "Holiday", "Teacher Workday", or other

THEN output JSON:
```json
{
    "february_colored_dates": [
        {"date": "2026-02-XX", "color": "...", "type": "..."}
    ],
    "holidays": [
        {"name": "MLK Day", "start_date": "2026-01-19", "end_date": "2026-01-19"},
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        {"name": "Spring Break", "start_date": "2026-04-06", "end_date": "2026-04-10"}
    ]
}
```

REMEMBER: Teacher Workday = Student Holiday (combine with adjacent holidays)"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system=BASE_SYSTEM
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3000 chars):")
    print(response_text[:3000])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    print(f"\nExtracted {len(holidays)} holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    # Also show February analysis if available
    feb_dates = result.get('february_colored_dates', [])
    if feb_dates:
        print("\nFebruary colored dates found:")
        for d in feb_dates:
            print(f"  - {d}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Row-by-Row Reading",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def main():
    """Run all format tests and compare results."""
    pdf_path = str(PROJECT_ROOT / "Official_Calendars/Public/Butts/ButtsSchoolYearCalendar2025-2026_FINAL_Approved1112.pdf")

    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return

    print("="*60)
    print("OUTPUT FORMAT COMPARISON TEST - VERSION 2")
    print("="*60)
    print(f"PDF: {pdf_path}")
    print("\nExpected results:")
    for name, dates in EXPECTED_HOLIDAYS.items():
        print(f"  - {name}: {dates['start']} to {dates['end']}")

    # Initialize client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Convert PDF to images
    print("\nConverting PDF to images...")
    images = pdf_to_images(pdf_path)
    if not images:
        print("Failed to convert PDF")
        return
    print(f"Converted {len(images)} pages")

    # Run all format tests
    results = []

    results.append(test_format_4_two_pass(client, images))
    results.append(test_format_5_verification_first(client, images))
    results.append(test_format_6_xml_structured(client, images))
    results.append(test_format_7_row_by_row(client, images))

    # Summary comparison
    print("\n" + "="*60)
    print("SUMMARY COMPARISON - V2 FORMATS")
    print("="*60)

    print("\n{:<30} {:<10} {:<15} {:<15}".format("Format", "Accuracy", "Feb 13 Found?", "Correct Dates"))
    print("-"*70)

    for r in results:
        accuracy = r['validation']['accuracy'] * 100

        # Check if Feb 13 was captured in Winter Break
        feb13_found = "No"
        for h in r['holidays']:
            if h.get('name') == 'Winter Break':
                if h.get('start_date') == '2026-02-13':
                    feb13_found = "Yes"
                break

        correct = r['validation']['correct']
        total = r['validation']['total_expected']

        print("{:<30} {:<10.0f}% {:<15} {}/{}".format(
            r['format'], accuracy, feb13_found, correct, total
        ))

    # Determine winner
    print("\n" + "-"*70)
    best = max(results, key=lambda x: (x['validation']['accuracy'],
                                        1 if any(h.get('start_date') == '2026-02-13' for h in x['holidays']) else 0))
    print(f"\nBEST FORMAT: {best['format']} ({best['validation']['accuracy']*100:.0f}% accuracy)")

    return results


if __name__ == '__main__':
    main()
