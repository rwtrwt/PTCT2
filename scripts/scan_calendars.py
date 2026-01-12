#!/usr/bin/env python3
"""
Batch Calendar Scanner

Scans new calendar PDFs and stores extracted holidays as 'ai_detected'.
Use this after verifying scanner accuracy with test_calendar_accuracy.py.

Run with: python scripts/scan_calendars.py [options]

Options:
    --year YEAR      School year to scan (default: 2025-2026)
    --max N          Limit to first N calendars
    --dry-run        Don't save to database, just show what would be extracted
"""

import os
import sys
import argparse
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
        print(f"Loaded environment from {env_path}")
except ImportError:
    pass

from app import create_app
from extensions import db
from models import CalendarFile, SchoolEntity, VerifiedHoliday
from scripts.improved_calendar_scanner import ImprovedCalendarScanner


def parse_date(date_str: str) -> date:
    """Parse a date string."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def scan_and_store_calendar(
    scanner: ImprovedCalendarScanner,
    cf: CalendarFile,
    dry_run: bool = False
) -> dict:
    """Scan a calendar file and store results."""
    entity = cf.school_entity
    pdf_path = str(PROJECT_ROOT / cf.file_path)

    if not os.path.exists(pdf_path):
        return {"error": f"File not found: {cf.file_path}"}

    # Scan the calendar
    result = scanner.scan_calendar(pdf_path, cf.school_year)

    if "error" in result:
        return {"error": result["error"]}

    holidays = result.get("holidays", [])
    confidence = result.get("confidence_avg", 0.8)

    stored_count = 0
    skipped_count = 0

    for h in holidays:
        try:
            start_date = parse_date(h.get("start_date", ""))
            end_date = parse_date(h.get("end_date", ""))
            holiday_confidence = h.get("confidence", confidence)

            # Check if this holiday already exists
            existing = VerifiedHoliday.query.filter_by(
                school_entity_id=entity.id,
                school_year=cf.school_year,
                name=h.get("name", ""),
                start_date=start_date
            ).first()

            if existing:
                skipped_count += 1
                continue

            if not dry_run:
                new_holiday = VerifiedHoliday(
                    school_entity_id=entity.id,
                    school_year=cf.school_year,
                    name=h.get("name", "Unknown"),
                    start_date=start_date,
                    end_date=end_date,
                    is_verified=False,
                    source="ai_detected",
                    confidence=holiday_confidence
                )
                db.session.add(new_holiday)
                stored_count += 1
            else:
                stored_count += 1  # Would store

        except (ValueError, TypeError) as e:
            print(f"    Warning: Could not parse holiday {h.get('name')}: {e}")
            continue

    if not dry_run:
        db.session.commit()

    return {
        "holidays_found": len(holidays),
        "stored": stored_count,
        "skipped": skipped_count,
        "confidence": confidence
    }


def main():
    parser = argparse.ArgumentParser(description="Batch scan calendars")
    parser.add_argument("--year", default="2025-2026", help="School year to scan")
    parser.add_argument("--max", type=int, help="Maximum calendars to scan")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    parser.add_argument("--skip-verified", action="store_true", default=True,
                       help="Skip entities that already have verified holidays")
    args = parser.parse_args()

    print("=" * 60)
    print("BATCH CALENDAR SCANNER")
    print("=" * 60)

    # Initialize scanner
    print("\nInitializing scanner...")
    scanner = ImprovedCalendarScanner()

    if not scanner.client:
        print("ERROR: Scanner not initialized. Please configure OpenAI API key.")
        return

    app = create_app()

    with app.app_context():
        # Get calendar files for the school year
        query = CalendarFile.query.filter_by(school_year=args.year)

        if args.skip_verified:
            # Get entity IDs that already have verified holidays
            verified_entity_ids = db.session.query(VerifiedHoliday.school_entity_id).filter_by(
                school_year=args.year,
                is_verified=True
            ).distinct().all()
            verified_ids = [v[0] for v in verified_entity_ids]

            if verified_ids:
                query = query.filter(~CalendarFile.school_entity_id.in_(verified_ids))
                print(f"Skipping {len(verified_ids)} entities with verified holidays")

        files = query.all()
        print(f"Found {len(files)} calendar files to scan")

        if args.max:
            files = files[:args.max]
            print(f"Limited to first {args.max} files")

        if args.dry_run:
            print("\n*** DRY RUN - No changes will be saved ***\n")

        # Scan each file
        success = 0
        errors = 0

        for i, cf in enumerate(files, 1):
            entity = cf.school_entity
            print(f"\n[{i}/{len(files)}] {entity.county if entity else 'Unknown'}: {cf.filename}")

            result = scan_and_store_calendar(scanner, cf, dry_run=args.dry_run)

            if "error" in result:
                print(f"  ERROR: {result['error']}")
                errors += 1
            else:
                print(f"  Found {result['holidays_found']} holidays")
                print(f"  Stored: {result['stored']}, Skipped: {result['skipped']}")
                print(f"  Confidence: {result['confidence']:.2f}")
                success += 1

        print("\n" + "=" * 60)
        print("SCAN COMPLETE")
        print("=" * 60)
        print(f"Successful: {success}")
        print(f"Errors: {errors}")

        if not args.dry_run:
            # Show summary of what was added
            detected_count = VerifiedHoliday.query.filter_by(
                school_year=args.year,
                source="ai_detected"
            ).count()
            print(f"\nTotal AI-detected holidays for {args.year}: {detected_count}")


if __name__ == "__main__":
    main()
