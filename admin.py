from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, make_response, current_app
from flask_login import login_required, current_user
from models import User, SchoolEntity, VerifiedHoliday, CalendarFile
from extensions import db
from datetime import datetime
from werkzeug.utils import secure_filename
import json
import os

admin = Blueprint('admin', __name__)

@admin.route('/admin')
@login_required
def admin_page():
    if not current_user.is_admin:
        flash('You do not have permission to access this page.')
        return redirect(url_for('main.home'))
    users = User.query.all()
    return render_template('admin.html', users=users)

@admin.route('/admin/toggle_admin/<int:user_id>')
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.')
        return redirect(url_for('main.home'))
    user = User.query.get(user_id)
    if user:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f'Admin status for {user.username} has been toggled.')
    return redirect(url_for('admin.admin_page'))

@admin.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.')
        return redirect(url_for('main.home'))
    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} has been deleted.')
    return redirect(url_for('admin.admin_page'))


@admin.route('/admin/school-calendars')
@login_required
def school_calendars():
    """Admin page for managing school calendars database."""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.')
        return redirect(url_for('main.home'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    entities_query = SchoolEntity.query.order_by(SchoolEntity.district_name)
    entities_paginated = entities_query.paginate(page=page, per_page=per_page, error_out=False)
    
    total_entities = SchoolEntity.query.count()
    public_districts = SchoolEntity.query.filter_by(entity_type='public_district').count()
    private_schools = SchoolEntity.query.filter_by(entity_type='private_school').count()

    all_entities = SchoolEntity.query.order_by(SchoolEntity.district_name).all()

    return render_template('admin_school_calendars.html',
        entities=entities_paginated.items,
        all_entities=all_entities,
        page=page,
        total_pages=entities_paginated.pages,
        total_entities=total_entities,
        public_districts=public_districts,
        private_schools=private_schools
    )


@admin.route('/admin/school-calendars/entity', methods=['POST'])
@login_required
def add_entity():
    """Add a new school entity."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.get_json()
        district_name = data.get('district_name', '').strip()
        entity_type = data.get('entity_type', 'public_district')
        county = data.get('county', '').strip() or None
        website = data.get('website', '').strip() or None
        
        if not district_name:
            return jsonify({'success': False, 'error': 'Entity name is required'}), 400
        
        normalized_name = SchoolEntity.normalize_name(district_name)
        
        existing = SchoolEntity.query.filter_by(
            entity_type=entity_type,
            normalized_name=normalized_name,
            county=county
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'An entity with this name already exists'}), 400
        
        entity = SchoolEntity(
            district_name=district_name,
            normalized_name=normalized_name,
            entity_type=entity_type,
            county=county,
            website=website
        )
        db.session.add(entity)
        db.session.commit()
        
        return jsonify({'success': True, 'entity_id': entity.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/entity/<int:entity_id>', methods=['PUT'])
@login_required
def update_entity(entity_id):
    """Update a school entity."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        entity = SchoolEntity.query.get_or_404(entity_id)
        data = request.get_json()
        
        district_name = data.get('district_name', '').strip()
        if district_name:
            entity.district_name = district_name
            entity.normalized_name = SchoolEntity.normalize_name(district_name)
        
        if 'entity_type' in data:
            entity.entity_type = data['entity_type']
        
        if 'county' in data:
            entity.county = data['county'].strip() or None

        if 'official_website' in data:
            entity.official_website = data['official_website'].strip() or None

        if 'calendar_page_url' in data:
            entity.calendar_page_url = data['calendar_page_url'].strip() or None

        entity.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/entity/<int:entity_id>', methods=['DELETE'])
@login_required
def delete_entity(entity_id):
    """Delete a school entity and all its calendars."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        entity = SchoolEntity.query.get_or_404(entity_id)
        db.session.delete(entity)
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/<int:entity_id>/edit')
@login_required
def edit_school_calendar(entity_id):
    """Edit page for a school entity and its holidays."""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.')
        return redirect(url_for('main.home'))

    entity = SchoolEntity.query.get_or_404(entity_id)

    # Get holidays grouped by school year
    holidays_by_year = {}
    holidays = VerifiedHoliday.query.filter_by(school_entity_id=entity.id).order_by(
        VerifiedHoliday.school_year.desc(),
        VerifiedHoliday.start_date
    ).all()

    for holiday in holidays:
        if holiday.school_year not in holidays_by_year:
            holidays_by_year[holiday.school_year] = []
        holidays_by_year[holiday.school_year].append(holiday)

    # Get calendar files
    calendar_files = CalendarFile.query.filter_by(school_entity_id=entity.id).order_by(
        CalendarFile.school_year.desc()
    ).all()

    available_years = sorted(holidays_by_year.keys(), reverse=True) if holidays_by_year else []

    return render_template('admin_edit_school.html',
        entity=entity,
        holidays_by_year=holidays_by_year,
        calendar_files=calendar_files,
        available_years=available_years
    )


@admin.route('/admin/school-calendars/<int:entity_id>/update', methods=['POST'])
@login_required
def update_school_info(entity_id):
    """Update school entity information."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        entity = SchoolEntity.query.get_or_404(entity_id)
        data = request.get_json()

        if 'district_name' in data and data['district_name'].strip():
            entity.district_name = data['district_name'].strip()
            entity.normalized_name = SchoolEntity.normalize_name(entity.district_name)
            entity.slug = SchoolEntity.generate_slug(entity.district_name)

        if 'county' in data:
            entity.county = data['county'].strip() or None

        if 'official_website' in data:
            entity.official_website = data['official_website'].strip() or None

        if 'calendar_page_url' in data:
            entity.calendar_page_url = data['calendar_page_url'].strip() or None

        entity.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'success': True, 'slug': entity.slug})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/<int:entity_id>/holidays', methods=['POST'])
@login_required
def add_holiday(entity_id):
    """Add a new holiday for a school entity."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        entity = SchoolEntity.query.get_or_404(entity_id)
        data = request.get_json()

        holiday = VerifiedHoliday(
            school_entity_id=entity.id,
            school_year=data['school_year'],
            name=data['name'],
            start_date=datetime.strptime(data['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        )
        db.session.add(holiday)
        db.session.commit()

        return jsonify({'success': True, 'holiday_id': holiday.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/holidays/<int:holiday_id>', methods=['PUT'])
@login_required
def update_holiday(holiday_id):
    """Update an existing holiday."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        holiday = VerifiedHoliday.query.get_or_404(holiday_id)
        data = request.get_json()

        if 'name' in data:
            holiday.name = data['name']
        if 'start_date' in data:
            holiday.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        if 'end_date' in data:
            holiday.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        if 'school_year' in data:
            holiday.school_year = data['school_year']

        holiday.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/holidays/<int:holiday_id>', methods=['DELETE'])
@login_required
def delete_holiday(holiday_id):
    """Delete a holiday."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        holiday = VerifiedHoliday.query.get_or_404(holiday_id)
        db.session.delete(holiday)
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@admin.route('/admin/school-calendars/<int:entity_id>/upload', methods=['POST'])
@login_required
def upload_calendar_file(entity_id):
    """Upload a calendar file for a school entity."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        entity = SchoolEntity.query.get_or_404(entity_id)

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        school_year = request.form.get('school_year', '').strip()

        if not school_year:
            return jsonify({'success': False, 'error': 'School year is required'}), 400

        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'File type not allowed. Use PDF, PNG, or JPG.'}), 400

        # Determine file extension and type
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        file_type = 'pdf' if file_ext == 'pdf' else file_ext

        # Create folder structure: Official_Calendars/Public/{County}/
        base_path = os.path.join(current_app.root_path, 'Official_Calendars', 'Public')
        county_folder = entity.county if entity.county else 'Other'
        folder_path = os.path.join(base_path, county_folder)

        # Create folder if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)

        # Generate filename: {DistrictName}{SchoolYear}.{ext}
        safe_name = secure_filename(entity.district_name.replace(' ', ''))
        filename = f"{safe_name}_{school_year.replace('-', '_')}.{file_ext}"
        file_path = os.path.join(folder_path, filename)

        # Save file
        file.save(file_path)

        # Get file size
        file_size = os.path.getsize(file_path)

        # Create database record
        relative_path = os.path.join('Official_Calendars', 'Public', county_folder, filename)
        calendar_file = CalendarFile(
            school_entity_id=entity.id,
            school_year=school_year,
            filename=filename,
            file_path=relative_path,
            file_type=file_type,
            file_size=file_size
        )
        db.session.add(calendar_file)
        db.session.commit()

        return jsonify({
            'success': True,
            'file_id': calendar_file.id,
            'filename': filename
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_calendar_file(file_id):
    """Delete a calendar file."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        calendar_file = CalendarFile.query.get_or_404(file_id)

        # Try to delete the actual file
        full_path = os.path.join(current_app.root_path, calendar_file.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)

        # Delete database record
        db.session.delete(calendar_file)
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


