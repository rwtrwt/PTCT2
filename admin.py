from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, make_response
from flask_login import login_required, current_user
from models import User, SchoolEntity, SchoolCalendar
from extensions import db
from datetime import datetime
import json

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
    total_calendars = SchoolCalendar.query.count()
    public_districts = SchoolEntity.query.filter_by(entity_type='public_district').count()
    private_schools = SchoolEntity.query.filter_by(entity_type='private_school').count()
    
    all_entities = SchoolEntity.query.order_by(SchoolEntity.district_name).all()
    
    return render_template('admin_school_calendars.html',
        entities=entities_paginated.items,
        all_entities=all_entities,
        page=page,
        total_pages=entities_paginated.pages,
        total_entities=total_entities,
        total_calendars=total_calendars,
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
        
        SchoolCalendar.query.filter_by(school_entity_id=entity_id).delete()
        db.session.delete(entity)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/calendar/<int:calendar_id>/json')
@login_required
def get_calendar_json(calendar_id):
    """Get calendar analysis JSON."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    calendar = SchoolCalendar.query.get_or_404(calendar_id)
    
    try:
        analysis = json.loads(calendar.analysis_json) if calendar.analysis_json else {}
        return jsonify({'success': True, 'analysis': analysis})
    except:
        return jsonify({'success': True, 'analysis': {}})


@admin.route('/admin/school-calendars/calendar/<int:calendar_id>/download')
@login_required
def download_calendar_json(calendar_id):
    """Download calendar analysis JSON as file."""
    if not current_user.is_admin:
        flash('Unauthorized')
        return redirect(url_for('main.home'))
    
    calendar = SchoolCalendar.query.get_or_404(calendar_id)
    
    try:
        analysis = json.loads(calendar.analysis_json) if calendar.analysis_json else {}
    except:
        analysis = {}
    
    response = make_response(json.dumps(analysis, indent=2))
    filename = f"{calendar.school_entity.district_name.replace(' ', '_')}_{calendar.school_year}_analysis.json"
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@admin.route('/admin/school-calendars/calendar/<int:calendar_id>', methods=['DELETE'])
@login_required
def delete_calendar(calendar_id):
    """Delete a calendar."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        calendar = SchoolCalendar.query.get_or_404(calendar_id)
        db.session.delete(calendar)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/calendar/<int:calendar_id>/reassign', methods=['POST'])
@login_required
def reassign_calendar(calendar_id):
    """Reassign a calendar to a different entity."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.get_json()
        new_entity_id = data.get('new_entity_id')
        
        if not new_entity_id:
            return jsonify({'success': False, 'error': 'New entity ID is required'}), 400
        
        calendar = SchoolCalendar.query.get_or_404(calendar_id)
        new_entity = SchoolEntity.query.get_or_404(new_entity_id)
        
        existing = SchoolCalendar.query.filter_by(
            school_entity_id=new_entity_id,
            school_year=calendar.school_year
        ).first()
        
        if existing and existing.id != calendar_id:
            return jsonify({'success': False, 'error': f'A calendar for {calendar.school_year} already exists for this entity'}), 400
        
        calendar.school_entity_id = new_entity_id
        calendar.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin.route('/admin/school-calendars/upload', methods=['POST'])
@login_required
def admin_upload_calendar():
    """Admin upload of a new calendar."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        entity_id = request.form.get('entity_id')
        school_year = request.form.get('school_year', '').strip()
        analyze = request.form.get('analyze') == 'on'
        
        if not entity_id or not school_year:
            return jsonify({'success': False, 'error': 'Entity and school year are required'}), 400
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'Valid PDF file is required'}), 400
        
        entity = SchoolEntity.query.get_or_404(entity_id)
        
        existing = SchoolCalendar.query.filter_by(
            school_entity_id=entity_id,
            school_year=school_year
        ).first()
        
        pdf_bytes = file.read()
        
        import hashlib
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        
        analysis_json = None
        status = 'uploaded'
        
        if analyze:
            try:
                from main import extract_text_from_pdf, extract_calendar_shading, analyze_school_calendar_two_pass, infer_missing_years
                
                extracted_text, is_scanned = extract_text_from_pdf(pdf_bytes)
                shading_info = extract_calendar_shading(pdf_bytes)
                calendar_result = analyze_school_calendar_two_pass(extracted_text, shading_info)
                calendar_result = infer_missing_years(calendar_result)
                
                calendar_result['_meta'] = {
                    'wasScanned': is_scanned,
                    'textLength': len(extracted_text),
                    'extractedAt': datetime.now().isoformat(),
                    'uploadedByAdmin': True
                }
                
                analysis_json = json.dumps(calendar_result)
                status = 'processed'
            except Exception as e:
                status = 'error'
                analysis_json = json.dumps({'error': str(e)})
        
        if existing:
            existing.source_filename = file.filename
            existing.file_hash = file_hash
            existing.analysis_json = analysis_json
            existing.analysis_version = '2.0'
            existing.analysis_generated_at = datetime.utcnow() if analyze else None
            existing.status = status
            existing.updated_at = datetime.utcnow()
        else:
            calendar = SchoolCalendar(
                school_entity_id=entity_id,
                school_year=school_year,
                source_filename=file.filename,
                file_hash=file_hash,
                analysis_json=analysis_json,
                analysis_version='2.0' if analyze else None,
                analysis_generated_at=datetime.utcnow() if analyze else None,
                uploaded_by_user_id=current_user.id,
                status=status
            )
            db.session.add(calendar)
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
