#!/usr/bin/env python3
"""
Test different output format requests - Version 3

Focus on formats that force Claude to describe what it SEES before categorizing.
Based on observation that Claude can see Feb 13 is colored when asked directly,
but misses it when asked to extract holidays.

New test formats:
8. Color-first approach - describe colors before inferring meaning
9. Negative verification - ask "which dates are NOT colored"
10. Grid coordinate approach - use row/column positions
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


def test_format_8_color_first(client, images):
    """
    Format 8: Color-first approach - describe colors before inferring meaning

    Theory: By asking Claude to describe WHAT IT SEES first without interpretation,
    it won't skip dates due to cognitive shortcuts.
    """
    print("\n" + "="*60)
    print("FORMAT 8: Color-First (Describe Before Interpret)")
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
        "text": """TASK: Describe the VISUAL APPEARANCE of each date cell in February 2026.

DO NOT interpret what the colors mean yet. Just describe what you SEE.

For each weekday (Mon-Fri) in February 2026, describe:
- The background color of the cell (white, yellow, blue, gray, etc.)
- Any text or numbers visible

Format your answer as:
Feb 2 (Mon): [background color], [text]
Feb 3 (Tue): [background color], [text]
... continue for all weekdays through Feb 27 ...

After listing all the colors, THEN interpret:
- Yellow background = Teacher Workday (no school for students)
- Blue background = Holiday (no school for students)
- White background = Regular school day

Finally, output Winter Break dates as JSON:
```json
{"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
```

Remember: If a date has ANY non-white background, students don't have school that day."""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system="You are a careful visual analyst. Describe exactly what you see before making interpretations."
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3000 chars):")
    print(response_text[:3000])

    # Extract just Winter Break for this test
    result = extract_json_from_response(response_text)

    # Build holidays list
    holidays = []
    if 'name' in result and result.get('name') == 'Winter Break':
        holidays.append(result)
    elif 'holidays' in result:
        holidays = result.get('holidays', [])

    # Add MLK Day and Spring Break with expected values for comparison
    # (This test focuses on Winter Break accuracy)
    if not any(h.get('name') == 'MLK Day' for h in holidays):
        holidays.append({"name": "MLK Day", "start_date": "2026-01-19", "end_date": "2026-01-19"})
    if not any(h.get('name') == 'Spring Break' for h in holidays):
        holidays.append({"name": "Spring Break", "start_date": "2026-04-06", "end_date": "2026-04-10"})

    print(f"\nExtracted holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Color-First Description",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_9_negative_verification(client, images):
    """
    Format 9: Negative verification - ask which dates are NOT colored

    Theory: Asking which dates DON'T have color may force more careful scanning.
    """
    print("\n" + "="*60)
    print("FORMAT 9: Negative Verification (Which are NOT colored)")
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
        "text": """For February 2026 in this calendar, I need you to identify which weekdays (Mon-Fri) are REGULAR SCHOOL DAYS (white/uncolored background).

List all February 2026 weekdays that have a WHITE/UNCOLORED background:
(These are days when students DO have school)

Then list all February 2026 weekdays that have ANY COLOR (yellow, blue, etc.):
(These are days when students DON'T have school)

Be very careful - look at EACH cell individually:
- Feb 9, 10, 11, 12, 13 - check each one
- Feb 16, 17, 18, 19, 20 - check each one

After your analysis, determine Winter Break (the February break around Presidents Day).
If Friday Feb 13 is colored AND Monday Feb 16 is colored, they form ONE continuous break (weekend bridges them).

Output as JSON:
```json
{
    "february_school_days": ["2026-02-02", "2026-02-03", ...],
    "february_no_school_days": ["2026-02-XX", ...],
    "holidays": [
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    ]
}
```"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system="You are a meticulous visual analyst. Check every single cell carefully."
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3000 chars):")
    print(response_text[:3000])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    # Add MLK Day and Spring Break with expected values
    if not any(h.get('name') == 'MLK Day' for h in holidays):
        holidays.append({"name": "MLK Day", "start_date": "2026-01-19", "end_date": "2026-01-19"})
    if not any(h.get('name') == 'Spring Break' for h in holidays):
        holidays.append({"name": "Spring Break", "start_date": "2026-04-06", "end_date": "2026-04-10"})

    print(f"\nExtracted holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    # Show the no-school days found
    no_school = result.get('february_no_school_days', [])
    if no_school:
        print(f"\nFebruary no-school days identified: {no_school}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Negative Verification",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_10_explicit_cell_check(client, images):
    """
    Format 10: Explicit cell-by-cell check with forced answers

    Theory: Force Claude to answer YES/NO for specific cells, no skipping allowed.
    """
    print("\n" + "="*60)
    print("FORMAT 10: Explicit Cell Check (Forced YES/NO)")
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
        "text": """MANDATORY CELL CHECK - You MUST answer each question below.

Look at the February 2026 section of the calendar. For each date listed below, answer whether the cell has a COLORED background (yellow, blue, gray - anything other than white).

ANSWER FORMAT: Date: YES (color) or NO (white)

Feb 9 (Mon):
Feb 10 (Tue):
Feb 11 (Wed):
Feb 12 (Thu):
Feb 13 (Fri):
Feb 14 (Sat):
Feb 15 (Sun):
Feb 16 (Mon):
Feb 17 (Tue):
Feb 18 (Wed):
Feb 19 (Thu):
Feb 20 (Fri):

IMPORTANT: Yellow = Teacher Workday = NO SCHOOL for students
Blue = Holiday = NO SCHOOL for students

Based on your answers above, what is the date range for Winter Break?
(Combine any adjacent colored weekdays - the weekend doesn't break the streak)

```json
{
    "cell_checks": {
        "2026-02-09": "YES/NO (color)",
        "2026-02-10": "YES/NO (color)",
        "2026-02-11": "YES/NO (color)",
        "2026-02-12": "YES/NO (color)",
        "2026-02-13": "YES/NO (color)",
        "2026-02-16": "YES/NO (color)",
        "2026-02-17": "YES/NO (color)",
        "2026-02-18": "YES/NO (color)",
        "2026-02-19": "YES/NO (color)",
        "2026-02-20": "YES/NO (color)"
    },
    "holidays": [
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    ]
}
```"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system="You must answer every question. Do not skip any cells. Look carefully at each date cell."
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3500 chars):")
    print(response_text[:3500])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    # Show cell checks
    cell_checks = result.get('cell_checks', {})
    if cell_checks:
        print("\nCell check results:")
        for date, status in sorted(cell_checks.items()):
            print(f"  {date}: {status}")

    # Add MLK Day and Spring Break with expected values
    if not any(h.get('name') == 'MLK Day' for h in holidays):
        holidays.append({"name": "MLK Day", "start_date": "2026-01-19", "end_date": "2026-01-19"})
    if not any(h.get('name') == 'Spring Break' for h in holidays):
        holidays.append({"name": "Spring Break", "start_date": "2026-04-06", "end_date": "2026-04-10"})

    print(f"\nExtracted holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Explicit Cell Check",
        "holidays": holidays,
        "validation": validation,
        "raw_response": response_text
    }


def test_format_11_known_fact_injection(client, images):
    """
    Format 11: Inject known facts to see if Claude agrees

    Theory: Tell Claude what we expect and ask it to verify/correct.
    """
    print("\n" + "="*60)
    print("FORMAT 11: Known Fact Verification")
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
        "text": """I have a claim about this calendar that I need you to VERIFY by looking at the image.

CLAIM: "Winter Break for Butts County 2025-2026 runs from February 13 to February 17, 2026.
This includes:
- Feb 13 (Friday) - Teacher Workday (yellow)
- Feb 14-15 - Weekend
- Feb 16 (Monday) - Presidents Day Holiday (blue)
- Feb 17 (Tuesday) - Teacher Workday (yellow)"

Please examine the February 2026 section of this calendar and tell me:

1. Is Feb 13 colored? If so, what color?
2. Is Feb 16 colored? If so, what color?
3. Is Feb 17 colored? If so, what color?
4. Based on what you see, is my claim CORRECT or INCORRECT?

If incorrect, what are the actual dates?

```json
{
    "verification": {
        "feb_13_colored": true/false,
        "feb_13_color": "color or none",
        "feb_16_colored": true/false,
        "feb_16_color": "color or none",
        "feb_17_colored": true/false,
        "feb_17_color": "color or none",
        "claim_correct": true/false
    },
    "holidays": [
        {"name": "Winter Break", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    ]
}
```"""
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        system="You are fact-checking claims against visual evidence. Be precise and accurate."
    )

    response_text = response.content[0].text
    print("\nRaw Response (first 3000 chars):")
    print(response_text[:3000])

    result = extract_json_from_response(response_text)
    holidays = result.get('holidays', [])

    # Show verification results
    verification = result.get('verification', {})
    if verification:
        print("\nVerification results:")
        for key, value in verification.items():
            print(f"  {key}: {value}")

    # Add MLK Day and Spring Break with expected values
    if not any(h.get('name') == 'MLK Day' for h in holidays):
        holidays.append({"name": "MLK Day", "start_date": "2026-01-19", "end_date": "2026-01-19"})
    if not any(h.get('name') == 'Spring Break' for h in holidays):
        holidays.append({"name": "Spring Break", "start_date": "2026-04-06", "end_date": "2026-04-10"})

    print(f"\nExtracted holidays:")
    for h in holidays:
        print(f"  - {h.get('name')}: {h.get('start_date')} to {h.get('end_date')}")

    validation = validate_results(holidays)
    print(f"\nValidation: {validation['correct']}/{validation['total_expected']} correct ({validation['accuracy']*100:.0f}%)")
    for name, detail in validation['details'].items():
        print(f"  - {name}: {detail}")

    return {
        "format": "Known Fact Verification",
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
    print("OUTPUT FORMAT COMPARISON TEST - VERSION 3")
    print("="*60)
    print(f"PDF: {pdf_path}")
    print("\nExpected results:")
    for name, dates in EXPECTED_HOLIDAYS.items():
        print(f"  - {name}: {dates['start']} to {dates['end']}")
    print("\nKEY TEST: Does Claude see Feb 13 as colored (yellow)?")

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

    results.append(test_format_8_color_first(client, images))
    results.append(test_format_9_negative_verification(client, images))
    results.append(test_format_10_explicit_cell_check(client, images))
    results.append(test_format_11_known_fact_injection(client, images))

    # Summary comparison
    print("\n" + "="*60)
    print("SUMMARY COMPARISON - V3 FORMATS")
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
