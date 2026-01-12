#!/usr/bin/env python3
"""
Test different output format requests to improve extraction accuracy.

Tests three prompt variations:
1. Ask for markdown table first, then JSON
2. Ask Claude to "think step by step" before outputting JSON
3. Ask for simple list format first, then convert to structured

Expected results for Butts County:
- MLK Day: 2026-01-19
- Winter Break: 2026-02-13 to 2026-02-17
- Spring Break: 2026-04-06 to 2026-04-10
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

# Base system prompt (used by all variations)
BASE_SYSTEM = """You are an expert school calendar analyst. Extract student holidays from this Georgia school calendar.

## HOLIDAY TYPES TO EXTRACT:
1. MLK Day - Single day in mid-January (3rd Monday, around Jan 15-21)
2. Winter Break - February break around Presidents Day (typically Feb 13-17)
3. Spring Break - 5 consecutive weekdays in late March or April

## CRITICAL RULES:
- Teacher Workdays = Student holidays (no school for students)
- If Friday is colored AND Monday is colored, combine into ONE break (weekend bridges them)
- ALWAYS check the Friday before any Monday holiday - often a Teacher Workday that extends the break

## WINTER BREAK (FEBRUARY) - MOST IMPORTANT:
- Presidents Day is the 3rd Monday in February (Feb 16, 2026)
- ALWAYS check Feb 13 (Friday before) - if it's colored, Winter Break starts Feb 13
- Teacher Workday on Feb 13 + Holiday on Feb 16 = Winter Break Feb 13-17

## COLOR CODING:
- Look at the legend to understand what each color means
- Any colored/shaded date that isn't a school day is a holiday
- Teacher Workday colors count as no-school days"""


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
    # Try markdown code blocks first
    json_match = re.search(r'```(?:json)?\s*(.*?)```', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except:
            pass

    # Find JSON object boundaries
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


def test_format_1_markdown_first(client, images):
    """
    Format 1: Ask for markdown table first, then JSON

    Theory: Having Claude organize data visually first may help it catch all dates.
    """
    print("\n" + "="*60)
    print("FORMAT 1: Markdown Table First, Then JSON")
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
        "text": """First, create a markdown table of ALL colored/shaded dates you can see in the calendar.

Use this format for the table:
| Month | Date | Day of Week | Color/Shading | Label (if any) |
|-------|------|-------------|---------------|----------------|

Include EVERY colored date, even if you're unsure what it means.

Pay special attention to:
- February 13 (Friday before Presidents Day)
- February 16-17 (Presidents Day area)
- April 6-10 (Spring Break area)

After the table, convert the relevant school holidays to this JSON format:
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
    print("\nRaw Response (first 2000 chars):")
    print(response_text[:2000])

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
        "format": "Markdown Table First",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_2_step_by_step(client, images):
    """
    Format 2: Ask Claude to "think step by step" before outputting JSON

    Theory: Chain-of-thought prompting may help Claude be more thorough.
    """
    print("\n" + "="*60)
    print("FORMAT 2: Think Step by Step, Then JSON")
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
        "text": """Think step by step to extract all school holidays. Show your reasoning process.

STEP 1: What colors/shadings are used in this calendar? What does the legend say each color means?

STEP 2: Scan FEBRUARY specifically. List every date that has any color/shading:
- Feb 13: [describe what you see]
- Feb 14: [describe what you see]
- Feb 15: [describe what you see]
- Feb 16: [describe what you see]
- Feb 17: [describe what you see]

STEP 3: Scan APRIL specifically. List dates with color/shading:
- Apr 6: [describe]
- Apr 7: [describe]
- Apr 8: [describe]
- Apr 9: [describe]
- Apr 10: [describe]

STEP 4: Based on your observations, what are the holiday date ranges?

STEP 5: Output your final answer as JSON:
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
        "format": "Step by Step Reasoning",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_3_simple_list_first(client, images):
    """
    Format 3: Ask for dates in simple list format first, then convert

    Theory: Simpler output format may reduce errors, then we convert.
    """
    print("\n" + "="*60)
    print("FORMAT 3: Simple List First, Then JSON")
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
        "text": """List ALL no-school days for students in a simple format.

For each no-school period, write ONE line like this:
HOLIDAY_NAME: START_DATE - END_DATE

Example format:
MLK Day: 2026-01-19 - 2026-01-19
Winter Break: 2026-02-XX - 2026-02-XX
Spring Break: 2026-04-XX - 2026-04-XX

IMPORTANT CHECKS before you answer:
1. Look at February 13 (Friday) - is it colored? If yes, include it in Winter Break.
2. Look at April 6-10 - are these dates colored for Spring Break?
3. Teacher Workdays = Student holidays (students don't have school)

After your simple list, also provide JSON:
```json
{
    "holidays": [
        {"name": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
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
    print("\nRaw Response (first 2000 chars):")
    print(response_text[:2000])

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
        "format": "Simple List First",
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
    print("OUTPUT FORMAT COMPARISON TEST")
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

    # Run all three format tests
    results = []

    results.append(test_format_1_markdown_first(client, images))
    results.append(test_format_2_step_by_step(client, images))
    results.append(test_format_3_simple_list_first(client, images))

    # Summary comparison
    print("\n" + "="*60)
    print("SUMMARY COMPARISON")
    print("="*60)

    print("\n{:<25} {:<10} {:<15} {:<15}".format("Format", "Accuracy", "Feb 13 Found?", "Correct Dates"))
    print("-"*65)

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

        print("{:<25} {:<10.0f}% {:<15} {}/{}".format(
            r['format'], accuracy, feb13_found, correct, total
        ))

    # Determine winner
    print("\n" + "-"*65)
    best = max(results, key=lambda x: (x['validation']['accuracy'],
                                        1 if any(h.get('start_date') == '2026-02-13' for h in x['holidays']) else 0))
    print(f"\nBEST FORMAT: {best['format']} ({best['validation']['accuracy']*100:.0f}% accuracy)")

    # Check specifically for Feb 13 issue
    print("\n" + "="*60)
    print("FEB 13 ANALYSIS")
    print("="*60)
    for r in results:
        print(f"\n{r['format']}:")
        winter_break = next((h for h in r['holidays'] if h.get('name') == 'Winter Break'), None)
        if winter_break:
            print(f"  Winter Break: {winter_break.get('start_date')} to {winter_break.get('end_date')}")
            if winter_break.get('start_date') == '2026-02-13':
                print("  STATUS: Feb 13 correctly included!")
            else:
                print(f"  STATUS: Feb 13 MISSED (starts at {winter_break.get('start_date')})")
        else:
            print("  Winter Break: NOT FOUND")

    return results


if __name__ == '__main__':
    main()
