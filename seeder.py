"""
Database Seeder Module

This module seeds the production database with school calendar data if the tables are empty.
It runs automatically on app startup to ensure production has the same data as development.
"""

import json
import os
from datetime import datetime
from extensions import db
from models import SchoolEntity, CalendarFile, VerifiedHoliday

SEED_FILE = 'seed_data.json'


def parse_date(date_str):
    """Parse ISO date string to date object."""
    if not date_str:
        return None
    if isinstance(date_str, str):
        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date() if 'T' not in date_str else datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    return date_str


def parse_datetime(dt_str):
    """Parse ISO datetime string to datetime object."""
    if not dt_str:
        return None
    if isinstance(dt_str, str):
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return datetime.fromisoformat(dt_str)
    return dt_str


def seed_database():
    """
    Seeds the database with school calendar data if tables are empty.
    Returns True if seeding occurred, False if tables already had data.
    """
    # Check if seed file exists
    if not os.path.exists(SEED_FILE):
        print(f"[Seeder] No seed file found at {SEED_FILE}")
        return False
    
    # Check if school_entity table is empty
    existing_count = SchoolEntity.query.count()
    if existing_count > 0:
        print(f"[Seeder] Database already has {existing_count} school entities. Skipping seed.")
        return False
    
    print("[Seeder] Database is empty. Starting seed process...")
    
    # Load seed data
    with open(SEED_FILE, 'r') as f:
        data = json.load(f)
    
    # Seed school_entity table
    school_entities = data.get('school_entity', [])
    print(f"[Seeder] Importing {len(school_entities)} school entities...")
    
    for entity in school_entities:
        school = SchoolEntity(
            id=entity['id'],
            entity_type=entity.get('entity_type', 'district'),
            district_name=entity['district_name'],
            normalized_name=entity.get('normalized_name'),
            county=entity.get('county'),
            nces_id=entity.get('nces_id'),
            is_active=entity.get('is_active', True),
            website=entity.get('website'),
            official_website=entity.get('official_website'),
            calendar_page_url=entity.get('calendar_page_url'),
            slug=entity.get('slug'),
            created_at=parse_datetime(entity.get('created_at')),
            updated_at=parse_datetime(entity.get('updated_at'))
        )
        db.session.add(school)
    
    db.session.commit()
    print(f"[Seeder] Imported {len(school_entities)} school entities")
    
    # Seed calendar_file table
    calendar_files = data.get('calendar_file', [])
    print(f"[Seeder] Importing {len(calendar_files)} calendar files...")
    
    for cf in calendar_files:
        cal_file = CalendarFile(
            id=cf['id'],
            school_entity_id=cf['school_entity_id'],
            school_year=cf.get('school_year'),
            filename=cf.get('filename'),
            file_path=cf.get('file_path'),
            file_type=cf.get('file_type'),
            file_size=cf.get('file_size'),
            created_at=parse_datetime(cf.get('created_at'))
        )
        db.session.add(cal_file)
    
    db.session.commit()
    print(f"[Seeder] Imported {len(calendar_files)} calendar files")
    
    # Seed verified_holiday table
    holidays = data.get('verified_holiday', [])
    print(f"[Seeder] Importing {len(holidays)} verified holidays...")
    
    for h in holidays:
        holiday = VerifiedHoliday(
            id=h['id'],
            school_entity_id=h['school_entity_id'],
            school_year=h.get('school_year'),
            name=h['name'],
            start_date=parse_date(h['start_date']),
            end_date=parse_date(h['end_date']),
            is_verified=h.get('is_verified', True),
            source=h.get('source'),
            confidence=h.get('confidence'),
            created_at=parse_datetime(h.get('created_at')),
            updated_at=parse_datetime(h.get('updated_at'))
        )
        db.session.add(holiday)
    
    db.session.commit()
    print(f"[Seeder] Imported {len(holidays)} verified holidays")
    
    # Reset sequences for PostgreSQL
    try:
        max_school = db.session.execute(db.text("SELECT MAX(id) FROM school_entity")).scalar() or 0
        max_calendar = db.session.execute(db.text("SELECT MAX(id) FROM calendar_file")).scalar() or 0
        max_holiday = db.session.execute(db.text("SELECT MAX(id) FROM verified_holiday")).scalar() or 0
        
        db.session.execute(db.text(f"SELECT setval('school_entity_id_seq', {max_school})"))
        db.session.execute(db.text(f"SELECT setval('calendar_file_id_seq', {max_calendar})"))
        db.session.execute(db.text(f"SELECT setval('verified_holiday_id_seq', {max_holiday})"))
        db.session.commit()
        print("[Seeder] Reset ID sequences")
    except Exception as e:
        print(f"[Seeder] Warning: Could not reset sequences: {e}")
    
    print("[Seeder] Database seeding complete!")
    return True
