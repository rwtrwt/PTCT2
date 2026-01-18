#!/usr/bin/env python3
"""
Script to import school calendar data from CSV into PostgreSQL.
"""
import csv
import re
import os
from datetime import datetime
from flask import Flask
from extensions import db
from models import SchoolEntity, VerifiedHoliday

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

def normalize_name(name):
    """Normalize school name for matching."""
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name

def parse_date_range(date_str):
    """Parse date range like '2026-01-19 to 2026-01-19' into start and end dates."""
    if not date_str or date_str.strip() == '' or 'off every' in date_str.lower():
        return None, None
    
    date_str = date_str.strip()
    if ' to ' in date_str:
        parts = date_str.split(' to ')
        try:
            start = datetime.strptime(parts[0].strip(), '%Y-%m-%d').date()
            end = datetime.strptime(parts[1].strip(), '%Y-%m-%d').date()
            return start, end
        except ValueError as e:
            print(f"  Warning: Could not parse date range '{date_str}': {e}")
            return None, None
    return None, None

def get_school_year(holiday_name):
    """Extract school year from holiday name like 'MLK Day 2026' -> '2025-2026'."""
    match = re.search(r'(\d{4})', holiday_name)
    if match:
        year = int(match.group(1))
        if 'Christmas' in holiday_name or 'Labor' in holiday_name or 'Fall' in holiday_name or 'Thanksgiving' in holiday_name:
            return f"{year}-{year+1}"
        else:
            return f"{year-1}-{year}"
    return None

def get_holiday_base_name(holiday_name):
    """Extract base holiday name without year like 'MLK Day 2026' -> 'MLK Day'."""
    return re.sub(r'\s*\d{4}\s*', '', holiday_name).strip()

def main():
    csv_path = 'attached_assets/Georgia_Private_and_Public_School_Calendars_-_Sheet3_1768695206481.csv'
    
    with app.app_context():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        school_names = rows[0][1:]
        counties = rows[1][1:]
        holiday_rows = rows[2:]
        
        print(f"Found {len(school_names)} schools")
        print(f"Found {len(holiday_rows)} holiday types")
        
        existing_entities = {e.normalized_name: e for e in SchoolEntity.query.all()}
        print(f"Existing entities in DB: {len(existing_entities)}")
        
        school_entity_map = {}
        created_count = 0
        matched_count = 0
        
        for i, (school_name, county) in enumerate(zip(school_names, counties)):
            school_name = school_name.strip()
            county = county.strip()
            
            if not school_name:
                continue
            
            normalized = normalize_name(school_name)
            
            found_entity = None
            for norm_name, entity in existing_entities.items():
                if norm_name == normalized:
                    found_entity = entity
                    break
                if entity.county and entity.county.lower() == county.lower():
                    if county.lower() in norm_name or county.lower() in normalized:
                        found_entity = entity
                        break
            
            if not found_entity:
                for norm_name, entity in existing_entities.items():
                    if county.lower() in norm_name.replace('_', ' '):
                        found_entity = entity
                        break
            
            if found_entity:
                school_entity_map[i] = found_entity
                matched_count += 1
                print(f"  Matched: '{school_name}' ({county}) -> {found_entity.district_name}")
            else:
                new_entity = SchoolEntity(
                    entity_type='public',
                    district_name=school_name,
                    normalized_name=normalized,
                    county=county,
                    is_active=True
                )
                db.session.add(new_entity)
                db.session.flush()
                school_entity_map[i] = new_entity
                existing_entities[normalized] = new_entity
                created_count += 1
                print(f"  Created: '{school_name}' ({county})")
        
        print(f"\nMatched: {matched_count}, Created: {created_count}")
        
        holidays_inserted = 0
        holidays_skipped = 0
        
        for holiday_row in holiday_rows:
            holiday_name = holiday_row[0].strip()
            if not holiday_name:
                continue
            
            base_name = get_holiday_base_name(holiday_name)
            school_year = get_school_year(holiday_name)
            
            if not school_year:
                print(f"  Could not determine school year for '{holiday_name}'")
                continue
            
            for i, date_range in enumerate(holiday_row[1:]):
                if i not in school_entity_map:
                    continue
                
                entity = school_entity_map[i]
                start_date, end_date = parse_date_range(date_range)
                
                if not start_date or not end_date:
                    continue
                
                existing = VerifiedHoliday.query.filter_by(
                    school_entity_id=entity.id,
                    school_year=school_year,
                    name=base_name,
                    start_date=start_date,
                    end_date=end_date
                ).first()
                
                if existing:
                    holidays_skipped += 1
                    continue
                
                holiday = VerifiedHoliday(
                    school_entity_id=entity.id,
                    school_year=school_year,
                    name=base_name,
                    start_date=start_date,
                    end_date=end_date,
                    is_verified=True,
                    source='csv_import'
                )
                db.session.add(holiday)
                holidays_inserted += 1
        
        db.session.commit()
        print(f"\nHolidays inserted: {holidays_inserted}")
        print(f"Holidays skipped (duplicates): {holidays_skipped}")
        
        total = VerifiedHoliday.query.count()
        print(f"Total holidays in database: {total}")

if __name__ == '__main__':
    main()
