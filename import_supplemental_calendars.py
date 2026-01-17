#!/usr/bin/env python3
"""
Import supplemental school calendar data from CSV into the database.
CSV format: County names as columns, holidays as rows, date ranges as values.
"""

import csv
import re
from datetime import datetime
from app import create_app
from extensions import db
from models import SchoolEntity, VerifiedHoliday

def parse_date_range(date_str):
    """Parse 'YYYY-MM-DD to YYYY-MM-DD' format."""
    if not date_str or date_str.strip() == '':
        return None, None

    date_str = date_str.strip()

    # Handle notes like "off every monday"
    if not re.match(r'^\d{4}-\d{2}-\d{2}', date_str):
        return None, None

    # Handle typos like "2028-02-187"
    date_str = re.sub(r'(\d{4}-\d{2}-)(\d{3,})', lambda m: m.group(1) + m.group(2)[:2], date_str)

    match = re.match(r'(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})', date_str)
    if match:
        try:
            start = datetime.strptime(match.group(1), '%Y-%m-%d').date()
            end = datetime.strptime(match.group(2), '%Y-%m-%d').date()
            return start, end
        except ValueError:
            return None, None

    return None, None

def get_school_year(start_date):
    """Determine school year from a date."""
    if start_date.month >= 8:
        return f"{start_date.year}-{start_date.year + 1}"
    else:
        return f"{start_date.year - 1}-{start_date.year}"

def normalize_county_name(county):
    """Normalize county name to match school entity format."""
    return county.lower().strip().replace(' ', '_')

def find_or_create_school_entity(county_name):
    """Find or create a SchoolEntity for a county."""
    normalized = normalize_county_name(county_name)

    # Try to find existing entity
    entity = SchoolEntity.query.filter(
        SchoolEntity.normalized_name.like(f"%{normalized}%")
    ).first()

    if not entity:
        # Create new entity
        display_name = f"{county_name} County Schools"
        entity = SchoolEntity(
            entity_type='public_district',
            district_name=display_name,
            normalized_name=normalized + '_county_schools',
            county=county_name,
            is_active=True
        )
        db.session.add(entity)
        db.session.flush()  # Get the ID
        print(f"  Created new entity: {display_name}")

    return entity

def import_csv(csv_path):
    """Import calendar data from CSV file."""
    app = create_app()

    with app.app_context():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)

            # Read header row to get county names
            header = next(reader)
            counties = header[1:]  # Skip "Holiday/Calendar" column

            print(f"Found {len(counties)} counties in CSV")

            # Create/find entities for each county
            entities = {}
            for county in counties:
                if county.strip():
                    entities[county] = find_or_create_school_entity(county)

            db.session.commit()

            # Process each holiday row
            holidays_added = 0
            holidays_skipped = 0

            for row in reader:
                if not row or not row[0]:
                    continue

                holiday_name = row[0].strip()
                print(f"\nProcessing: {holiday_name}")

                for i, date_str in enumerate(row[1:], start=0):
                    if i >= len(counties):
                        break

                    county = counties[i]
                    if not county.strip() or county not in entities:
                        continue

                    start_date, end_date = parse_date_range(date_str)
                    if not start_date or not end_date:
                        continue

                    entity = entities[county]
                    school_year = get_school_year(start_date)

                    # Check if this holiday already exists
                    existing = VerifiedHoliday.query.filter_by(
                        school_entity_id=entity.id,
                        name=holiday_name,
                        start_date=start_date,
                        end_date=end_date
                    ).first()

                    if existing:
                        holidays_skipped += 1
                        continue

                    # Create new verified holiday
                    holiday = VerifiedHoliday(
                        school_entity_id=entity.id,
                        school_year=school_year,
                        name=holiday_name,
                        start_date=start_date,
                        end_date=end_date,
                        is_verified=True,
                        source='imported',
                        confidence=1.0
                    )
                    db.session.add(holiday)
                    holidays_added += 1
                    print(f"  + {county}: {start_date} to {end_date}")

            db.session.commit()

            print(f"\n{'='*50}")
            print(f"Import complete!")
            print(f"  Holidays added: {holidays_added}")
            print(f"  Holidays skipped (already exist): {holidays_skipped}")
            print(f"  Total entities: {len(entities)}")

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        csv_path = '/Users/russell/Library/CloudStorage/OneDrive-Daniels&TaylorP.C/Work/Claude/IN/Supplemental Georgia Private and Public School Calendars - Sheet3.csv'
    else:
        csv_path = sys.argv[1]

    print(f"Importing from: {csv_path}")
    import_csv(csv_path)
