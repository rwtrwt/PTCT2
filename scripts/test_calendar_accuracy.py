#!/usr/bin/env python3
"""
Calendar Scanner Accuracy Test Framework

Tests the improved AI calendar scanner against verified calendar data.
Measures accuracy by comparing extracted holidays to known correct dates.

Run with: python scripts/test_calendar_accuracy.py

Accuracy metrics:
- Per-holiday accuracy: Does extracted date match verified date exactly?
- Per-calendar accuracy: Percentage of holidays extracted correctly for each school
- Overall accuracy: Target is 100% accuracy on 75%+ of calendars
"""

import os
import sys
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

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

from app import create_app
from models import CalendarFile, SchoolEntity
from verified_calendars import VERIFIED_HOLIDAYS, VERIFIED_SCHOOLS, COUNTY_KEYWORDS


@dataclass
class HolidayMatch:
    """Result of comparing an extracted holiday to verified data."""
    name: str
    extracted_start: Optional[date] = None
    extracted_end: Optional[date] = None
    verified_start: Optional[date] = None
    verified_end: Optional[date] = None
    start_match: bool = False
    end_match: bool = False
    start_diff_days: int = 0
    end_diff_days: int = 0
    is_missing: bool = False  # Not found in extraction
    is_extra: bool = False    # Found in extraction but not in verified


@dataclass
class CalendarTestResult:
    """Test results for a single school calendar."""
    school_name: str
    county: str
    school_year: str
    pdf_path: str
    total_verified_holidays: int = 0
    total_extracted_holidays: int = 0
    exact_matches: int = 0
    partial_matches: int = 0  # Within 1-2 days
    misses: int = 0
    extras: int = 0
    holiday_matches: List[HolidayMatch] = field(default_factory=list)
    extraction_time_seconds: float = 0.0
    error: Optional[str] = None

    @property
    def accuracy_pct(self) -> float:
        """Calculate accuracy percentage."""
        if self.total_verified_holidays == 0:
            return 0.0
        return (self.exact_matches / self.total_verified_holidays) * 100

    @property
    def is_perfect(self) -> bool:
        """True if 100% accuracy on this calendar."""
        return self.exact_matches == self.total_verified_holidays and self.total_verified_holidays > 0


def normalize_school_name(name: str) -> str:
    """Normalize school name for matching."""
    return name.lower().strip()


def find_verified_data_for_county(county: str, school_year: str) -> Optional[Tuple[str, List[Dict]]]:
    """
    Find verified holiday data for a county.
    Returns (school_name, holidays) or None if not found.
    """
    county_lower = county.lower()

    # Check if this county is in COUNTY_KEYWORDS
    if county_lower in COUNTY_KEYWORDS:
        school_key = COUNTY_KEYWORDS[county_lower]
        year_data = VERIFIED_HOLIDAYS.get(school_year, {})
        if school_key in year_data:
            display_name = VERIFIED_SCHOOLS.get(school_key, school_key.title())
            return (display_name, year_data[school_key])

    # Try direct lookup in verified data
    year_data = VERIFIED_HOLIDAYS.get(school_year, {})
    for school_key, holidays in year_data.items():
        if county_lower in school_key:
            display_name = VERIFIED_SCHOOLS.get(school_key, school_key.title())
            return (display_name, holidays)

    return None


def parse_date(date_str: str) -> Optional[date]:
    """Parse a date string in various formats."""
    if not date_str:
        return None

    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def compare_holidays(
    extracted: List[Dict],
    verified: List[Dict]
) -> List[HolidayMatch]:
    """
    Compare extracted holidays against verified data.
    Returns list of HolidayMatch objects.
    """
    matches = []

    # Index verified holidays by normalized name
    verified_by_name = {}
    for v in verified:
        name = v.get('name', '').lower()
        # Also add common aliases
        names_to_check = [name]
        if 'mlk' in name:
            names_to_check.extend(['martin luther king', 'mlk day', 'mlk'])
        if 'winter break' in name:
            names_to_check.extend(['presidents day', 'february break'])
        if 'spring break' in name:
            names_to_check.append('spring break')
        if 'christmas' in name:
            names_to_check.extend(['winter break', 'christmas break', 'holiday break'])
        if 'thanksgiving' in name:
            names_to_check.append('thanksgiving')
        if 'fall break' in name:
            names_to_check.append('fall break')

        for n in names_to_check:
            verified_by_name[n] = v

    # Track which verified holidays were matched
    matched_verified = set()

    # Compare each extracted holiday
    for ext in extracted:
        ext_name = ext.get('name', '').lower()
        ext_start = parse_date(ext.get('start_date') or ext.get('startDate', ''))
        ext_end = parse_date(ext.get('end_date') or ext.get('endDate', ''))

        # Find matching verified holiday
        ver = None
        for name_variant in [ext_name] + [k for k in verified_by_name if k in ext_name or ext_name in k]:
            if name_variant in verified_by_name:
                ver = verified_by_name[name_variant]
                matched_verified.add(ver.get('name', ''))
                break

        if ver:
            ver_start = parse_date(ver.get('startDate', ''))
            ver_end = parse_date(ver.get('endDate', ''))

            start_match = ext_start == ver_start if ext_start and ver_start else False
            end_match = ext_end == ver_end if ext_end and ver_end else False

            start_diff = abs((ext_start - ver_start).days) if ext_start and ver_start else 999
            end_diff = abs((ext_end - ver_end).days) if ext_end and ver_end else 999

            matches.append(HolidayMatch(
                name=ext.get('name', ext_name.title()),
                extracted_start=ext_start,
                extracted_end=ext_end,
                verified_start=ver_start,
                verified_end=ver_end,
                start_match=start_match,
                end_match=end_match,
                start_diff_days=start_diff,
                end_diff_days=end_diff
            ))
        else:
            # Extracted but not in verified data (extra)
            matches.append(HolidayMatch(
                name=ext.get('name', ext_name.title()),
                extracted_start=ext_start,
                extracted_end=ext_end,
                is_extra=True
            ))

    # Add missing holidays (in verified but not extracted)
    for ver in verified:
        if ver.get('name', '') not in matched_verified:
            matches.append(HolidayMatch(
                name=ver.get('name', ''),
                verified_start=parse_date(ver.get('startDate', '')),
                verified_end=parse_date(ver.get('endDate', '')),
                is_missing=True
            ))

    return matches


def test_single_calendar(
    scanner,
    pdf_path: str,
    county: str,
    school_year: str
) -> CalendarTestResult:
    """Test scanner on a single calendar PDF."""
    import time

    result = CalendarTestResult(
        school_name="",
        county=county,
        school_year=school_year,
        pdf_path=pdf_path
    )

    # Find verified data for this county
    verified_data = find_verified_data_for_county(county, school_year)
    if not verified_data:
        result.error = f"No verified data for {county} {school_year}"
        return result

    school_name, verified_holidays = verified_data
    result.school_name = school_name
    result.total_verified_holidays = len(verified_holidays)

    # Run scanner
    start_time = time.time()
    try:
        scan_result = scanner.scan_calendar(pdf_path, school_year)
        result.extraction_time_seconds = time.time() - start_time
    except Exception as e:
        result.error = str(e)
        result.extraction_time_seconds = time.time() - start_time
        return result

    if 'error' in scan_result:
        result.error = scan_result['error']
        return result

    extracted_holidays = scan_result.get('holidays', [])
    result.total_extracted_holidays = len(extracted_holidays)

    # Compare holidays
    matches = compare_holidays(extracted_holidays, verified_holidays)
    result.holiday_matches = matches

    # Calculate stats
    for m in matches:
        if m.is_missing:
            result.misses += 1
        elif m.is_extra:
            result.extras += 1
        elif m.start_match and m.end_match:
            result.exact_matches += 1
        elif m.start_diff_days <= 2 and m.end_diff_days <= 2:
            result.partial_matches += 1
        else:
            result.misses += 1

    return result


def run_full_test(max_calendars: int = None, school_year: str = "2025-2026") -> Dict:
    """
    Run tests on all calendars with verified data.

    Args:
        max_calendars: Limit number of calendars to test (for quick iteration)
        school_year: School year to test

    Returns:
        Dictionary with test summary and detailed results
    """
    from scripts.improved_calendar_scanner import ImprovedCalendarScanner

    print("=" * 60)
    print("CALENDAR SCANNER ACCURACY TEST")
    print("=" * 60)

    # Initialize scanner
    print("\nInitializing scanner...")
    scanner = ImprovedCalendarScanner()

    if not scanner.client:
        return {
            "error": "Scanner not initialized - OpenAI API key required",
            "results": []
        }

    app = create_app()
    results = []

    with app.app_context():
        # Find calendar files with matching school year
        files = CalendarFile.query.filter_by(school_year=school_year).all()
        print(f"Found {len(files)} calendar files for {school_year}")

        # Filter to only those with verified data
        testable_files = []
        for cf in files:
            entity = cf.school_entity
            if entity and entity.county:
                verified = find_verified_data_for_county(entity.county, school_year)
                if verified:
                    testable_files.append((cf, entity, verified[0]))

        print(f"Found {len(testable_files)} files with verified data available")

        if max_calendars:
            testable_files = testable_files[:max_calendars]
            print(f"Testing first {max_calendars} calendars")

        # Test each calendar
        for i, (cf, entity, school_name) in enumerate(testable_files, 1):
            pdf_full_path = str(PROJECT_ROOT / cf.file_path)

            if not os.path.exists(pdf_full_path):
                print(f"\n[{i}/{len(testable_files)}] SKIP: File not found: {cf.file_path}")
                continue

            print(f"\n[{i}/{len(testable_files)}] Testing: {entity.county} ({school_name})")

            result = test_single_calendar(
                scanner,
                pdf_full_path,
                entity.county,
                school_year
            )
            results.append(result)

            # Print quick summary
            if result.error:
                print(f"  ERROR: {result.error}")
            else:
                status = "PERFECT" if result.is_perfect else f"{result.accuracy_pct:.0f}%"
                print(f"  Result: {status} ({result.exact_matches}/{result.total_verified_holidays} exact)")
                print(f"  Time: {result.extraction_time_seconds:.1f}s")

    # Calculate overall stats
    perfect_count = sum(1 for r in results if r.is_perfect)
    total_tested = len([r for r in results if not r.error])
    success_rate = (perfect_count / total_tested * 100) if total_tested > 0 else 0

    summary = {
        "school_year": school_year,
        "total_calendars_tested": total_tested,
        "perfect_accuracy_count": perfect_count,
        "perfect_accuracy_pct": success_rate,
        "target_met": success_rate >= 75.0,
        "average_accuracy": sum(r.accuracy_pct for r in results if not r.error) / total_tested if total_tested > 0 else 0,
        "errors": len([r for r in results if r.error])
    }

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total calendars tested: {summary['total_calendars_tested']}")
    print(f"Perfect accuracy (100%): {summary['perfect_accuracy_count']} ({summary['perfect_accuracy_pct']:.1f}%)")
    print(f"Average accuracy: {summary['average_accuracy']:.1f}%")
    print(f"Errors: {summary['errors']}")
    print(f"\nTarget (75% with 100% accuracy): {'MET' if summary['target_met'] else 'NOT MET'}")
    print("=" * 60)

    return {
        "summary": summary,
        "results": [
            {
                "school": r.school_name,
                "county": r.county,
                "accuracy_pct": r.accuracy_pct,
                "exact_matches": r.exact_matches,
                "total_holidays": r.total_verified_holidays,
                "is_perfect": r.is_perfect,
                "error": r.error,
                "time_seconds": r.extraction_time_seconds
            }
            for r in results
        ]
    }


def generate_detailed_report(results: Dict, output_path: str = None) -> str:
    """Generate a detailed accuracy report."""
    lines = []
    lines.append("=" * 80)
    lines.append("DETAILED CALENDAR SCANNER ACCURACY REPORT")
    lines.append("=" * 80)
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")

    summary = results.get("summary", {})
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"School Year: {summary.get('school_year', 'N/A')}")
    lines.append(f"Calendars Tested: {summary.get('total_calendars_tested', 0)}")
    lines.append(f"Perfect Accuracy: {summary.get('perfect_accuracy_count', 0)} ({summary.get('perfect_accuracy_pct', 0):.1f}%)")
    lines.append(f"Average Accuracy: {summary.get('average_accuracy', 0):.1f}%")
    lines.append(f"Target Met: {'YES' if summary.get('target_met') else 'NO'}")
    lines.append("")

    lines.append("RESULTS BY SCHOOL")
    lines.append("-" * 40)

    for r in sorted(results.get("results", []), key=lambda x: -x.get("accuracy_pct", 0)):
        status = "PERFECT" if r.get("is_perfect") else f"{r.get('accuracy_pct', 0):.0f}%"
        lines.append(f"{r.get('county', 'Unknown'):20} {status:8} ({r.get('exact_matches', 0)}/{r.get('total_holidays', 0)})")

        if r.get("error"):
            lines.append(f"  ERROR: {r['error']}")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, 'w') as f:
            f.write(report)
        print(f"Report saved to: {output_path}")

    return report


def main():
    """Run the test suite."""
    import argparse

    parser = argparse.ArgumentParser(description="Test calendar scanner accuracy")
    parser.add_argument("--max", type=int, help="Maximum calendars to test")
    parser.add_argument("--year", default="2025-2026", help="School year to test")
    parser.add_argument("--report", type=str, help="Output report file path")
    args = parser.parse_args()

    results = run_full_test(max_calendars=args.max, school_year=args.year)

    if args.report:
        generate_detailed_report(results, args.report)
    else:
        # Print to console
        print("\n")
        print(generate_detailed_report(results))


if __name__ == '__main__':
    main()
