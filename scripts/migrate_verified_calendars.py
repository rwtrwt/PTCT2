#!/usr/bin/env python3
"""
Migration script to import verified calendar data into database.
Run with: python scripts/migrate_verified_calendars.py
"""

import os
import sys
import re
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import SchoolEntity, VerifiedHoliday, CalendarFile
from verified_calendars import VERIFIED_SCHOOLS, VERIFIED_HOLIDAYS, COUNTY_KEYWORDS

# Official website URLs for Georgia school districts (researched)
OFFICIAL_URLS = {
    "baldwin county schools": {
        "website": "https://www.baldwin.k12.ga.us",
        "calendar": "https://www.baldwin.k12.ga.us/page/calendars"
    },
    "barrow county school system": {
        "website": "https://www.barrow.k12.ga.us",
        "calendar": "https://www.barrow.k12.ga.us/page/district-calendar"
    },
    "cherokee county school district": {
        "website": "https://www.cherokeek12.net",
        "calendar": "https://www.cherokeek12.net/Page/2"
    },
    "clarke county school district": {
        "website": "https://www.clarke.k12.ga.us",
        "calendar": "https://www.clarke.k12.ga.us/Page/1633"
    },
    "clayton county public schools": {
        "website": "https://www.clayton.k12.ga.us",
        "calendar": "https://www.clayton.k12.ga.us/Page/24417"
    },
    "cobb county school district": {
        "website": "https://www.cobbk12.org",
        "calendar": "https://www.cobbk12.org/page/222/calendars"
    },
    "dawson county schools": {
        "website": "https://www.dawsoncountyschools.org",
        "calendar": "https://www.dawsoncountyschools.org/Page/2"
    },
    "dekalb county school district": {
        "website": "https://www.dekalbschoolsga.org",
        "calendar": "https://www.dekalbschoolsga.org/calendars/"
    },
    "douglas county school system": {
        "website": "https://www.dcssga.org",
        "calendar": "https://www.dcssga.org/Page/2"
    },
    "forsyth county schools": {
        "website": "https://www.forsyth.k12.ga.us",
        "calendar": "https://www.forsyth.k12.ga.us/Page/3"
    },
    "fulton county schools": {
        "website": "https://www.fultonschools.org",
        "calendar": "https://www.fultonschools.org/calendars"
    },
    "greater atlanta christian schools": {
        "website": "https://www.greateratlantachristian.org",
        "calendar": "https://www.greateratlantachristian.org/academics/calendar"
    },
    "greene county schools": {
        "website": "https://www.greene.k12.ga.us",
        "calendar": "https://www.greene.k12.ga.us/Page/1"
    },
    "gwinnett county public schools": {
        "website": "https://www.gcpsk12.org",
        "calendar": "https://www.gcpsk12.org/calendar"
    },
    "hall county schools": {
        "website": "https://www.hallco.org",
        "calendar": "https://www.hallco.org/web/index.php/calendar/"
    },
    "hancock county schools": {
        "website": "https://www.hancock.k12.ga.us",
        "calendar": "https://www.hancock.k12.ga.us"
    },
    "henry county schools": {
        "website": "https://www.henry.k12.ga.us",
        "calendar": "https://www.henry.k12.ga.us/calendars"
    },
    "houston county schools": {
        "website": "https://www.hcbe.net",
        "calendar": "https://www.hcbe.net/Page/2"
    },
    "jackson county school system": {
        "website": "https://www.jackson.k12.ga.us",
        "calendar": "https://www.jackson.k12.ga.us/Page/2"
    },
    "jasper county schools": {
        "website": "https://www.jasper.k12.ga.us",
        "calendar": "https://www.jasper.k12.ga.us"
    },
    "jones county schools": {
        "website": "https://www.jones.k12.ga.us",
        "calendar": "https://www.jones.k12.ga.us/Page/2"
    },
    "lumpkin county schools": {
        "website": "https://www.lumpkinschools.com",
        "calendar": "https://www.lumpkinschools.com/Page/2"
    },
    "madison county schools": {
        "website": "https://www.madison.k12.ga.us",
        "calendar": "https://www.madison.k12.ga.us/Page/2"
    },
    "morgan county schools": {
        "website": "https://www.morgan.k12.ga.us",
        "calendar": "https://www.morgan.k12.ga.us"
    },
    "newton county schools": {
        "website": "https://www.newtoncountyschools.org",
        "calendar": "https://www.newtoncountyschools.org/Page/2"
    },
    "oconee county schools": {
        "website": "https://www.oconeeschools.org",
        "calendar": "https://www.oconeeschools.org/Page/2"
    },
    "oglethorpe county schools": {
        "website": "https://www.oglethorpe.k12.ga.us",
        "calendar": "https://www.oglethorpe.k12.ga.us"
    },
    "putnam county schools": {
        "website": "https://www.putnam.k12.ga.us",
        "calendar": "https://www.putnam.k12.ga.us/Page/2"
    },
    "rockdale county public schools": {
        "website": "https://www.rockdaleschools.org",
        "calendar": "https://www.rockdaleschools.org/Page/2"
    },
    "walton county school district": {
        "website": "https://www.walton.k12.ga.us",
        "calendar": "https://www.walton.k12.ga.us/Page/2"
    },
    "washington county schools": {
        "website": "https://www.washington.k12.ga.us",
        "calendar": "https://www.washington.k12.ga.us"
    },
    "wilkinson county schools": {
        "website": "https://www.wilkinson.k12.ga.us",
        "calendar": "https://www.wilkinson.k12.ga.us"
    },
}


def get_county_from_name(school_name):
    """Extract county name from school district name."""
    # Most Georgia school names follow pattern: "{County} County ..."
    match = re.search(r'^(\w+)\s+county', school_name, re.IGNORECASE)
    if match:
        return match.group(1).title()
    # For non-county schools like "Greater Atlanta Christian"
    return None


def import_schools():
    """Import school entities from VERIFIED_SCHOOLS."""
    print("\n=== Importing School Entities ===")
    created = 0
    updated = 0

    for normalized_name, display_name in VERIFIED_SCHOOLS.items():
        county = get_county_from_name(display_name)
        slug = SchoolEntity.generate_slug(display_name)

        # Get official URLs
        urls = OFFICIAL_URLS.get(normalized_name, {})

        # Check if entity exists
        entity = SchoolEntity.query.filter_by(normalized_name=normalized_name.replace(' ', '_')).first()

        if not entity:
            entity = SchoolEntity(
                entity_type='public_district' if county else 'private_school',
                district_name=display_name,
                normalized_name=SchoolEntity.normalize_name(display_name),
                county=county,
                is_active=True,
                slug=slug,
                official_website=urls.get('website'),
                calendar_page_url=urls.get('calendar')
            )
            db.session.add(entity)
            created += 1
            print(f"  Created: {display_name} (slug: {slug})")
        else:
            # Update existing entity with new fields
            entity.slug = slug
            entity.official_website = urls.get('website')
            entity.calendar_page_url = urls.get('calendar')
            if county and not entity.county:
                entity.county = county
            updated += 1
            print(f"  Updated: {display_name}")

    db.session.commit()
    print(f"\nSchool entities: {created} created, {updated} updated")
    return created + updated


def import_holidays():
    """Import verified holidays from VERIFIED_HOLIDAYS."""
    print("\n=== Importing Verified Holidays ===")
    created = 0
    skipped = 0

    for school_year, schools in VERIFIED_HOLIDAYS.items():
        print(f"\nSchool Year: {school_year}")

        for school_name, holidays in schools.items():
            # Find the school entity
            entity = SchoolEntity.query.filter(
                SchoolEntity.normalized_name.like(f"%{school_name.replace(' ', '_').split('_')[0]}%")
            ).first()

            if not entity:
                # Try exact match
                entity = SchoolEntity.query.filter_by(
                    normalized_name=SchoolEntity.normalize_name(VERIFIED_SCHOOLS.get(school_name, school_name))
                ).first()

            if not entity:
                print(f"  WARNING: No entity found for {school_name}")
                skipped += len(holidays)
                continue

            # Delete existing holidays for this entity/year to avoid duplicates
            VerifiedHoliday.query.filter_by(
                school_entity_id=entity.id,
                school_year=school_year
            ).delete()

            # Import holidays
            for holiday in holidays:
                vh = VerifiedHoliday(
                    school_entity_id=entity.id,
                    school_year=school_year,
                    name=holiday['name'],
                    start_date=datetime.strptime(holiday['startDate'], '%Y-%m-%d').date(),
                    end_date=datetime.strptime(holiday['endDate'], '%Y-%m-%d').date()
                )
                db.session.add(vh)
                created += 1

            print(f"  {entity.district_name}: {len(holidays)} holidays")

    db.session.commit()
    print(f"\nHolidays: {created} created, {skipped} skipped")
    return created


def extract_school_year(filename):
    """Extract school year from filename."""
    # Match patterns like 2025-2026, 2025-26, 25-26
    patterns = [
        r'(\d{4})-(\d{4})',  # 2025-2026
        r'(\d{4})-(\d{2})',  # 2025-26
        r'(\d{2})-(\d{2})',  # 25-26
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            year1, year2 = match.groups()
            # Normalize to YYYY-YYYY format
            if len(year1) == 2:
                year1 = '20' + year1
            if len(year2) == 2:
                year2 = '20' + year2
            elif len(year2) == 4:
                pass  # Already full year
            return f"{year1}-{year2}"

    return None


def import_calendar_files():
    """Import calendar PDF/image files from Official_Calendars folder."""
    print("\n=== Importing Calendar Files ===")

    calendars_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'Official_Calendars', 'Public'
    )

    if not os.path.exists(calendars_dir):
        print(f"  ERROR: Directory not found: {calendars_dir}")
        return 0

    created = 0
    skipped = 0

    # Get all entities for matching
    entities = {e.county.lower() if e.county else '': e for e in SchoolEntity.query.all()}

    for county_folder in os.listdir(calendars_dir):
        county_path = os.path.join(calendars_dir, county_folder)
        if not os.path.isdir(county_path):
            continue

        # Find matching entity by county name
        entity = entities.get(county_folder.lower())
        if not entity:
            # Try to find by partial match
            for key, e in entities.items():
                if county_folder.lower() in key or key in county_folder.lower():
                    entity = e
                    break

        if not entity:
            print(f"  WARNING: No entity found for county folder: {county_folder}")
            continue

        # Import files from this county folder
        for filename in os.listdir(county_path):
            file_path = os.path.join(county_path, filename)
            if not os.path.isfile(file_path):
                continue

            # Determine file type
            ext = filename.lower().split('.')[-1]
            if ext not in ('pdf', 'png', 'jpg', 'jpeg'):
                continue

            file_type = 'pdf' if ext == 'pdf' else ext

            # Extract school year from filename
            school_year = extract_school_year(filename)
            if not school_year:
                print(f"    WARNING: Could not extract year from: {filename}")
                school_year = "Unknown"

            # Get file size
            file_size = os.path.getsize(file_path)

            # Check if already exists
            relative_path = f"Official_Calendars/Public/{county_folder}/{filename}"
            existing = CalendarFile.query.filter_by(
                school_entity_id=entity.id,
                file_path=relative_path
            ).first()

            if existing:
                skipped += 1
                continue

            cf = CalendarFile(
                school_entity_id=entity.id,
                school_year=school_year,
                filename=filename,
                file_path=relative_path,
                file_type=file_type,
                file_size=file_size
            )
            db.session.add(cf)
            created += 1

        print(f"  {county_folder}: {entity.district_name}")

    db.session.commit()
    print(f"\nCalendar files: {created} created, {skipped} skipped (duplicates)")
    return created


def main():
    """Run the migration."""
    print("=" * 60)
    print("Verified Calendar Data Migration")
    print("=" * 60)

    app = create_app()
    with app.app_context():
        # Import in order
        num_schools = import_schools()
        num_holidays = import_holidays()
        num_files = import_calendar_files()

        print("\n" + "=" * 60)
        print("Migration Complete!")
        print(f"  Schools: {num_schools}")
        print(f"  Holidays: {num_holidays}")
        print(f"  Files: {num_files}")
        print("=" * 60)


if __name__ == '__main__':
    main()
