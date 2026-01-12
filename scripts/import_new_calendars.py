#!/usr/bin/env python3
"""
Import script for new school calendar PDFs.
Auto-creates SchoolEntity records for new counties and imports CalendarFile records.

Run with: python scripts/import_new_calendars.py
"""

import os
import sys
import re
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import SchoolEntity, CalendarFile


def extract_school_year(filename):
    """Extract school year from filename."""
    patterns = [
        r'(\d{4})-(\d{4})',  # 2025-2026
        r'(\d{4})-(\d{2})',  # 2025-26
        r'(\d{2})-(\d{2})',  # 25-26
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            year1, year2 = match.groups()
            if len(year1) == 2:
                year1 = '20' + year1
            if len(year2) == 2:
                year2 = '20' + year2
            return f"{year1}-{year2}"

    return None


def create_entity_for_county(county_name):
    """Create a new SchoolEntity for a county that doesn't exist."""
    # Generate district name (e.g., "Bibb" -> "Bibb County Schools")
    display_name = f"{county_name} County Schools"
    normalized_name = SchoolEntity.normalize_name(display_name)
    slug = SchoolEntity.generate_slug(display_name)

    entity = SchoolEntity(
        entity_type='public_district',
        district_name=display_name,
        normalized_name=normalized_name,
        county=county_name,
        is_active=True,
        slug=slug
    )
    db.session.add(entity)
    db.session.flush()  # Get the ID assigned
    return entity


def import_calendars():
    """Import all calendar files, creating entities as needed."""
    print("\n=== Importing Calendar Files ===")

    calendars_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'Official_Calendars', 'Public'
    )

    if not os.path.exists(calendars_dir):
        print(f"  ERROR: Directory not found: {calendars_dir}")
        return 0, 0, 0

    entities_created = 0
    files_created = 0
    files_skipped = 0

    # Get existing entities indexed by county (lowercase)
    existing_entities = {}
    for entity in SchoolEntity.query.all():
        if entity.county:
            existing_entities[entity.county.lower()] = entity

    # Process each county folder
    county_folders = sorted(os.listdir(calendars_dir))
    print(f"\nFound {len(county_folders)} county folders")

    for county_folder in county_folders:
        county_path = os.path.join(calendars_dir, county_folder)
        if not os.path.isdir(county_path):
            continue

        county_name = county_folder.title()  # Normalize: "bibb" -> "Bibb"
        county_key = county_folder.lower()

        # Find or create entity
        entity = existing_entities.get(county_key)

        if not entity:
            # Check for partial matches (e.g., "Dekalb" vs "DeKalb")
            for key, e in existing_entities.items():
                if county_key in key or key in county_key:
                    entity = e
                    break

        if not entity:
            # Create new entity for this county
            entity = create_entity_for_county(county_name)
            existing_entities[county_key] = entity
            entities_created += 1
            print(f"  NEW ENTITY: {entity.district_name} (slug: {entity.slug})")

        # Import files from this county folder
        files_in_folder = 0
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
                files_skipped += 1
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
            files_created += 1
            files_in_folder += 1

        if files_in_folder > 0:
            print(f"  {county_name}: {files_in_folder} files imported")

    db.session.commit()
    return entities_created, files_created, files_skipped


def show_summary():
    """Show summary of what's in the database."""
    print("\n=== Database Summary ===")

    total_entities = SchoolEntity.query.count()
    total_files = CalendarFile.query.count()

    # Count by school year
    from sqlalchemy import func
    year_counts = db.session.query(
        CalendarFile.school_year,
        func.count(CalendarFile.id)
    ).group_by(CalendarFile.school_year).all()

    print(f"\nTotal School Entities: {total_entities}")
    print(f"Total Calendar Files: {total_files}")
    print("\nFiles by School Year:")
    for year, count in sorted(year_counts):
        print(f"  {year}: {count} files")

    # Show entities without calendar files
    entities_without_files = db.session.query(SchoolEntity).outerjoin(
        CalendarFile
    ).filter(CalendarFile.id == None).count()

    if entities_without_files > 0:
        print(f"\nEntities without calendar files: {entities_without_files}")


def main():
    """Run the import."""
    print("=" * 60)
    print("New Calendar Import Script")
    print("=" * 60)

    app = create_app()
    with app.app_context():
        entities_created, files_created, files_skipped = import_calendars()

        print("\n" + "=" * 60)
        print("Import Complete!")
        print(f"  New entities created: {entities_created}")
        print(f"  New files imported: {files_created}")
        print(f"  Files skipped (duplicates): {files_skipped}")
        print("=" * 60)

        show_summary()


if __name__ == '__main__':
    main()
