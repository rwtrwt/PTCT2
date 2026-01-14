from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session
from markupsafe import Markup
from flask_login import login_required, current_user
from models import User, CalendarSave, GuestToken, SchoolEntity, VerifiedHoliday, CalendarFile
from extensions import db, mail
from flask_mail import Message
from datetime import datetime
from flask import request, flash, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import io
import json
import tempfile
import logging

logger = logging.getLogger(__name__)

# Verified school calendar lookup
from verified_calendars import find_verified_school, get_verified_calendar_24_months, detect_school_year, get_display_name

# PDF processing imports - wrapped to handle missing dependencies gracefully
pdfplumber = None
pytesseract = None
convert_from_bytes = None
Image = None
OpenAI = None
cv2 = None
np = None

try:
    import pdfplumber
    import pytesseract
    from pdf2image import convert_from_bytes
    from PIL import Image
    from openai import OpenAI
    import cv2
    import numpy as np
except ImportError as e:
    logger.warning(f"Optional PDF/AI dependencies not available: {e}")

_openai_client = None

def is_production_environment():
    """Detect if we're running in production (deployed) environment."""
    replit_deployment = os.environ.get("REPLIT_DEPLOYMENT", "")
    replit_dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    return replit_deployment == "1" or not replit_dev_domain

def get_openai_client():
    """
    Get or create OpenAI client lazily.
    Priority:
    1. User's own OPENAI_API_KEY (works everywhere, billed to user)
    2. Replit integration (works in both development and production)
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    
    if not OpenAI:
        logger.error("OpenAI library not available")
        return None
    
    user_api_key = os.environ.get("OPENAI_API_KEY", "")
    replit_api_key = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY", "")
    replit_base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL", "")
    
    if user_api_key:
        try:
            _openai_client = OpenAI(api_key=user_api_key)
            logger.info("OpenAI client initialized with user API key (direct to OpenAI)")
            return _openai_client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client with user key: {e}")
    
    if replit_api_key and replit_base_url:
        try:
            _openai_client = OpenAI(api_key=replit_api_key, base_url=replit_base_url)
            logger.info(f"OpenAI client initialized with Replit integration (base_url: {replit_base_url[:30]}...)")
            return _openai_client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client with Replit integration: {e}")
    
    logger.error(f"OpenAI client not available - User key: {bool(user_api_key)}, Replit key: {bool(replit_api_key)}, Replit URL: {bool(replit_base_url)}")
    return None

main = Blueprint('main', __name__)

def get_client_ip():
    """Get real client IP, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

def get_or_create_guest_token(ip_address):
    """Get existing guest token or create new one with 10 tokens."""
    guest = GuestToken.query.filter_by(ip_address=ip_address).first()
    if not guest:
        guest = GuestToken(ip_address=ip_address, tokens=10)
        db.session.add(guest)
        db.session.commit()
    return guest

def send_guest_data_email(guest, data_type):
    """Send email notification when guest provides contact info."""
    try:
        subject = f"New Guest Lead - {data_type} Collected"
        body = f"""
New guest lead information collected:

IP Address: {guest.ip_address}
Email: {guest.email or 'Not provided'}
Phone: {guest.phone or 'Not provided'}
Contact Permission: {'Yes' if guest.contact_permission else 'No'}
Data Type Collected: {data_type}
Created: {guest.created_at}
Updated: {guest.updated_at}
"""
        msg = Message(subject=subject, recipients=['russell@danielstaylor.com'], body=body)
        mail.send(msg)
        logger.info(f"Guest data email sent for IP {guest.ip_address}")
    except Exception as e:
        logger.error(f"Failed to send guest data email: {e}")

def link_guest_to_user(user):
    """Link any matching guest tokens to a newly registered user."""
    guests = GuestToken.query.filter(
        (GuestToken.email == user.email) | 
        (GuestToken.ip_address == get_client_ip())
    ).all()
    for guest in guests:
        if not guest.linked_user_id:
            guest.linked_user_id = user.id
    db.session.commit()

def get_effective_date():
    """
    Get the effective current date for calendar operations.
    Returns the admin override date if set by an admin user, otherwise today's date.
    """
    from datetime import date
    if current_user.is_authenticated and current_user.is_admin:
        override_date_str = session.get('admin_date_override')
        if override_date_str:
            try:
                return datetime.strptime(override_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
    return date.today()

@main.route('/admin/date_override', methods=['GET'])
@login_required
def get_admin_date_override():
    """Get the current admin date override setting."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    override_date = session.get('admin_date_override')
    return jsonify({
        'override_active': override_date is not None,
        'override_date': override_date,
        'actual_date': datetime.now().strftime('%Y-%m-%d')
    })

@main.route('/admin/date_override', methods=['POST'])
@login_required
def set_admin_date_override():
    """Set an admin date override for testing purposes."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    override_date = data.get('date')
    
    if override_date:
        try:
            datetime.strptime(override_date, '%Y-%m-%d')
            session['admin_date_override'] = override_date
            return jsonify({
                'success': True,
                'message': f'Date override set to {override_date}',
                'override_date': override_date
            })
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    else:
        return jsonify({'error': 'Date is required'}), 400

@main.route('/admin/date_override', methods=['DELETE'])
@login_required
def clear_admin_date_override():
    """Clear the admin date override."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    session.pop('admin_date_override', None)
    return jsonify({
        'success': True,
        'message': 'Date override cleared',
        'actual_date': datetime.now().strftime('%Y-%m-%d')
    })

@main.route('/health')
def health():
    """Health check endpoint for debugging production issues."""
    import os
    user_key = os.environ.get('OPENAI_API_KEY', '')
    replit_key = os.environ.get('AI_INTEGRATIONS_OPENAI_API_KEY', '')
    replit_url = os.environ.get('AI_INTEGRATIONS_OPENAI_BASE_URL', '')
    
    status = {
        "status": "ok",
        "database_configured": bool(os.environ.get('DATABASE_URL')),
        "database_type": os.environ.get('DATABASE_URL', 'sqlite:///mydatabase.db').split('://')[0] if os.environ.get('DATABASE_URL') else 'sqlite',
        "is_production": os.environ.get('REPLIT_DEPLOYMENT') == '1',
        "has_dev_domain": bool(os.environ.get('REPLIT_DEV_DOMAIN')),
        "user_openai_key_present": bool(user_key),
        "replit_openai_key_present": bool(replit_key),
        "replit_openai_base_url_present": bool(replit_url),
        "replit_base_url_is_localhost": "localhost" in replit_url if replit_url else False,
        "pdf_library_available": pdfplumber is not None,
        "ocr_library_available": pytesseract is not None,
        "openai_library_available": OpenAI is not None
    }
    try:
        db.session.execute(db.text('SELECT 1'))
        status["database_connected"] = True
    except Exception as e:
        status["database_connected"] = False
        status["database_error"] = str(e)
    return jsonify(status)

@main.route('/test_openai')
def test_openai():
    """Test OpenAI connection in production."""
    try:
        client = get_openai_client()
        if not client:
            return jsonify({
                "success": False,
                "error": "OpenAI client could not be initialized",
                "user_key_present": bool(os.environ.get('OPENAI_API_KEY')),
                "is_production": is_production_environment()
            })
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'test ok' in exactly 2 words"}],
            max_tokens=10,
            timeout=30
        )
        result = response.choices[0].message.content
        return jsonify({
            "success": True,
            "response": result,
            "model_used": response.model
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        })

@main.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('home.html')

@main.route('/dashboard')
@login_required
def dashboard():
    print(f"Dashboard route accessed. User authenticated: {current_user.is_authenticated}")
    print(f"Current user ID: {current_user.get_id()}")
    return render_template('dashboard.html')

@main.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('main.dashboard'))
    users = User.query.all()
    return render_template('admin_dashboard.html', users=users)

@main.route('/admin/toggle_block', methods=['POST'])
@login_required
def toggle_block():
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    user = User.query.get(data.get('user_id'))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.is_super_admin:
        return jsonify({'error': 'Cannot block super admin'}), 403
    user.is_blocked = data.get('block', False)
    db.session.commit()
    return jsonify({'success': True, 'message': f'User {"blocked" if user.is_blocked else "unblocked"} successfully'})

@main.route('/admin/toggle_admin', methods=['POST'])
@login_required
def toggle_admin():
    if not current_user.is_super_admin:
        return jsonify({'error': 'Only super admins can manage admin privileges'}), 403
    data = request.get_json()
    user = User.query.get(data.get('user_id'))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.is_super_admin:
        return jsonify({'error': 'Cannot modify super admin privileges'}), 403
    user.is_admin = data.get('make_admin', False)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Admin privileges {"granted" if user.is_admin else "revoked"} successfully'})

@main.route('/admin/update_credits', methods=['POST'])
@login_required
def update_credits():
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    user = User.query.get(data.get('user_id'))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    user.token = data.get('credits', 0)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Credits updated to {user.token}'})



@main.route('/calendar_generator')
@login_required
def calendar_generator():
    # Assuming 'current_user' is the logged-in user instance
    if current_user.subscription_type == 'paid':
        return render_template('calendar_generator.html')
    elif current_user.subscription_type == 'free':
        if current_user.token > 0:
            # Decrement the token by 1
            current_user.token -= 1
            db.session.commit()  # Save the updated token count
            return render_template('calendar_generator.html')
        else:
            flash(Markup('You need more tokens to access this feature. <a href="/subscription" style="color: #22c55e; font-weight: bold;">Subscribe now</a> for unlimited access!'), 'warning')
            return redirect(url_for('main.home'))  # Redirect to a different page if no tokens
    else:
        flash('Invalid subscription type.', 'danger')
        return redirect(url_for('main.home'))

@main.route('/ai-calendar')
def ai_calendar():
    is_loading_save = request.args.get('load') is not None
    
    if current_user.is_authenticated:
        if current_user.subscription_type == 'paid':
            return render_template('ai_calendar.html', is_guest=False)
        elif current_user.subscription_type == 'free':
            if is_loading_save or current_user.token > 0:
                if not is_loading_save:
                    current_user.token -= 1
                    db.session.commit()
                return render_template('ai_calendar.html', is_guest=False)
            else:
                flash(Markup('You need more tokens to access this feature. <a href="/subscription" style="color: #22c55e; font-weight: bold;">Subscribe now</a> for unlimited access!'), 'warning')
                return redirect(url_for('main.home'))
        else:
            flash('Invalid subscription type.', 'danger')
            return redirect(url_for('main.home'))
    else:
        ip_address = get_client_ip()
        guest = get_or_create_guest_token(ip_address)
        
        if guest.tokens > 0:
            guest.tokens -= 1
            db.session.commit()
            return render_template('ai_calendar.html', is_guest=True, guest_tokens=guest.tokens, 
                                   needs_email=False, needs_phone=False)
        elif not guest.email:
            return render_template('ai_calendar.html', is_guest=True, guest_tokens=0,
                                   needs_email=True, needs_phone=False)
        elif not guest.phone:
            return render_template('ai_calendar.html', is_guest=True, guest_tokens=0,
                                   needs_email=False, needs_phone=True)
        else:
            flash(Markup('You have used all available tokens. <a href="/register" style="color: #22c55e; font-weight: bold;">Register now</a> to get more tokens or <a href="/subscription" style="color: #22c55e; font-weight: bold;">subscribe</a> for unlimited access!'), 'warning')
            return redirect(url_for('auth.register'))


@main.route('/user-guide')
def user_guide():
    """User guide for AI calendar tools."""
    return render_template('user_guide.html')


@main.route('/technical-docs')
def technical_docs():
    """Technical documentation for AI calendar tools."""
    return render_template('technical_docs.html')


@main.route('/how-georgia-counts-parenting-time-days')
def how_georgia_counts_parenting_time():
    """Pillar page explaining Georgia's parenting time counting methodology."""
    return render_template('how_georgia_counts_parenting_time.html')


@main.route('/api/guest/status')
def guest_status():
    """Get current guest token status."""
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'tokens': current_user.token})
    
    ip_address = get_client_ip()
    guest = get_or_create_guest_token(ip_address)
    
    return jsonify({
        'authenticated': False,
        'tokens': guest.tokens,
        'has_email': bool(guest.email),
        'has_phone': bool(guest.phone),
        'needs_email': guest.tokens <= 0 and not guest.email,
        'needs_phone': guest.tokens <= 0 and guest.email and not guest.phone
    })


@main.route('/api/guest/submit-email', methods=['POST'])
def submit_guest_email():
    """Submit email for additional tokens."""
    if current_user.is_authenticated:
        return jsonify({'error': 'Already authenticated'}), 400
    
    data = request.get_json()
    email = data.get('email', '').strip()
    
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400
    
    ip_address = get_client_ip()
    guest = get_or_create_guest_token(ip_address)
    
    if guest.email:
        return jsonify({'error': 'Email already submitted'}), 400
    
    guest.email = email
    guest.tokens += 5
    db.session.commit()
    
    send_guest_data_email(guest, 'Email')
    
    return jsonify({
        'success': True,
        'tokens': guest.tokens,
        'message': 'Thanks! You received 5 additional tokens.'
    })


@main.route('/api/guest/submit-phone', methods=['POST'])
def submit_guest_phone():
    """Submit phone for additional tokens."""
    if current_user.is_authenticated:
        return jsonify({'error': 'Already authenticated'}), 400
    
    data = request.get_json()
    phone = data.get('phone', '').strip()
    contact_permission = data.get('contact_permission', False)
    
    if not phone or len(phone) < 7:
        return jsonify({'error': 'Valid phone number required'}), 400
    
    if not contact_permission:
        return jsonify({'error': 'Contact permission required to receive tokens'}), 400
    
    ip_address = get_client_ip()
    guest = get_or_create_guest_token(ip_address)
    
    if guest.phone:
        return jsonify({'error': 'Phone already submitted'}), 400
    
    guest.phone = phone
    guest.contact_permission = contact_permission
    guest.tokens += 10
    db.session.commit()
    
    send_guest_data_email(guest, 'Phone')
    
    return jsonify({
        'success': True,
        'tokens': guest.tokens,
        'message': 'Thanks! You received 10 additional tokens.'
    })

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # Handle custom H4 content update
        custom_h4 = request.form.get('custom_h4')
        if custom_h4 is not None:
            current_user.custom_h4 = custom_h4
            db.session.commit()
            flash('Your custom H4 content has been updated successfully!', 'success')

        # Handle password change
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')

        if current_password and new_password:
            if check_password_hash(current_user.password_hash, current_password):
                current_user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Your password has been changed successfully!', 'success')
            else:
                flash('Current password is incorrect. Please try again.', 'danger')

    guest_journey = GuestToken.query.filter_by(linked_user_id=current_user.id).first()
    return render_template('profile.html', current_user=current_user, guest_journey=guest_journey)


@main.route('/subscription')
@login_required
def subscription():
    return render_template('subscription.html')


@main.route('/saves')
@login_required
def saves():
    user_saves = CalendarSave.query.filter_by(user_id=current_user.id).order_by(CalendarSave.updated_at.desc()).all()
    return render_template('saves.html', saves=user_saves)


@main.route('/api/saves', methods=['GET'])
@login_required
def get_saves():
    user_saves = CalendarSave.query.filter_by(user_id=current_user.id).order_by(CalendarSave.updated_at.desc()).all()
    return jsonify([s.to_dict() for s in user_saves])


@main.route('/api/saves', methods=['POST'])
@login_required
def create_save():
    data = request.get_json()
    if not data or 'name' not in data or 'config_data' not in data:
        return jsonify({'error': 'Name and config_data are required'}), 400
    
    new_save = CalendarSave(
        user_id=current_user.id,
        name=data['name'],
        config_data=data['config_data']
    )
    db.session.add(new_save)
    db.session.commit()
    return jsonify(new_save.to_dict()), 201


@main.route('/api/saves/<int:save_id>', methods=['GET'])
@login_required
def get_save(save_id):
    save = CalendarSave.query.filter_by(id=save_id, user_id=current_user.id).first()
    if not save:
        return jsonify({'error': 'Save not found'}), 404
    return jsonify(save.to_dict())


@main.route('/api/saves/<int:save_id>', methods=['PUT'])
@login_required
def update_save(save_id):
    save = CalendarSave.query.filter_by(id=save_id, user_id=current_user.id).first()
    if not save:
        return jsonify({'error': 'Save not found'}), 404
    
    data = request.get_json()
    if 'name' in data:
        save.name = data['name']
    if 'config_data' in data:
        save.config_data = data['config_data']
    
    save.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(save.to_dict())


@main.route('/api/saves/<int:save_id>', methods=['DELETE'])
@login_required
def delete_save(save_id):
    save = CalendarSave.query.filter_by(id=save_id, user_id=current_user.id).first()
    if not save:
        return jsonify({'error': 'Save not found'}), 404
    
    db.session.delete(save)
    db.session.commit()
    return jsonify({'success': True})


@main.route('/api/saves/<int:save_id>/copy', methods=['POST'])
@login_required
def copy_save(save_id):
    save = CalendarSave.query.filter_by(id=save_id, user_id=current_user.id).first()
    if not save:
        return jsonify({'error': 'Save not found'}), 404
    
    new_save = CalendarSave(
        user_id=current_user.id,
        name=f"{save.name} (Copy)",
        config_data=save.config_data
    )
    db.session.add(new_save)
    db.session.commit()
    return jsonify(new_save.to_dict()), 201


SYSTEM_PROMPT = """You are a Georgia family law document analyzer specializing in parenting plans and custody agreements. Analyze the provided parenting plan and extract scheduling information to populate a parenting time calculator.

STEP 1: IDENTIFY THE PARTIES (DO THIS FIRST - CRITICAL)
Before analyzing any schedules, you MUST identify the parties and determine who is the custodial parent:

A. Extract from Case Caption:
   - Find "Petitioner" or "Plaintiff" name (usually listed first, before "v." or "vs.")
   - Find "Respondent" or "Defendant" name (listed after "v." or "vs.")
   - Example: "JOHN SMITH, Petitioner v. JANE DOE, Respondent"

B. Determine Gender of Each Party:
   - Use common name gender associations (e.g., Ramon, John, Michael = male; Genanna, Jane, Mary = female)
   - Look for pronouns or explicit references like "the Father" or "the Mother" referring to a named party
   - Note: Petitioner can be either Mother or Father

C. Find Primary Physical Custodian Designation:
   - Look for "Primary Physical Custodian" section with checkboxes like:
     "[ ] Mother  [X] Father  [ ] Joint"
   - The checked [X] option indicates who has primary physical custody
   - Also look for phrases like "primary physical custody shall be with the Father/Mother"

D. Map to Parent A and Parent B:
   DECISION TABLE:
   | Primary Physical Custodian | Parent A (Custodial) | Parent B (Non-Custodial) |
   |---------------------------|---------------------|-------------------------|
   | [X] Father checked        | Father's name       | Mother's name           |
   | [X] Mother checked        | Mother's name       | Father's name           |
   | [X] Joint checked         | Use context clues   | Use context clues       |

   Example: If "RAMON GAUBERT, Petitioner" is male (Father) and "[X] Father" is checked for Primary Physical Custodian:
   - Parent A = Ramon Gaubert (Father, Custodial)
   - Parent B = The other party (Mother, Non-Custodial)

E. Include Your Reasoning:
   In "identifiedParties" and "analysisNotes", explain HOW you determined who is Parent A vs Parent B

CRITICAL DEFINITIONS:
- "Parent A" = Custodial Parent (primary physical custody)
- "Parent B" = Non-custodial Parent (the parent exercising parenting time/visitation)
- The tool calculates Parent B's parenting time percentage
- All schedule assignments (holidays, breaks, etc.) reference "Mother" or "Father" in documents
- You must translate "Mother" → Parent A or B based on who has custody
- You must translate "Father" → Parent A or B based on who has custody

Return a JSON object with this exact structure:

{
  "confidence": "high" | "medium" | "low",
  "analysisNotes": "explanation of ambiguities or assumptions",
  
  "regularWeeklySchedule": {
    "pattern": "first-third" | "second-fourth" | "alternating-odd" | "alternating-even" | "every" | "Omit",
    "beginDay": "friday",
    "endDay": "sunday",
    "reasoning": "direct quote from document"
  },
  
  "recurringDaytimePeriods": {
    "frequency": "first-third-recurring" | "second-fourth-recurring" | "every" | "every-other" | "Omit",
    "everyOtherType": "odd" | "even" | null,
    "days": {
      "monday": { "enabled": false, "hours": 0 },
      "tuesday": { "enabled": false, "hours": 0 },
      "wednesday": { "enabled": true, "hours": 4 },
      "thursday": { "enabled": false, "hours": 0 },
      "friday": { "enabled": false, "hours": 0 },
      "saturday": { "enabled": false, "hours": 0 },
      "sunday": { "enabled": false, "hours": 0 }
    },
    "reasoning": "quote"
  },
  
  "springBreak": {
    "evenYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" },
    "oddYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" }
  },
  
  "fallBreak": {
    "evenYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" },
    "oddYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" }
  },
  
  "thanksgivingBreak": {
    "evenYears": {
      "parent": "A" | "B" | "Split" | "Omit",
      "firstSplitParent": "A" | "B" | null,
      "reasoning": "quote"
    },
    "oddYears": {
      "parent": "A" | "B" | "Split" | "Omit",
      "firstSplitParent": "A" | "B" | null,
      "reasoning": "quote"
    }
  },
  
  "christmasBreak": {
    "evenYears": {
      "parent": "A" | "B" | "Split" | "Omit",
      "firstSplitParent": "A" | "B" | null,
      "reasoning": "quote"
    },
    "oddYears": {
      "parent": "A" | "B" | "Split" | "Omit",
      "firstSplitParent": "A" | "B" | null,
      "reasoning": "quote"
    }
  },
  
  "winterBreak": {
    "evenYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" },
    "oddYears": { "parent": "A" | "B" | "Omit", "reasoning": "quote" }
  },
  
  "summerSchedule": {
    "evenYears": {
      "option": "1week" | "2weeks" | "3weeks" | "4weeks" | "alternating" | "All" | "Omit",
      "weeks": null,
      "reasoning": "quote"
    },
    "oddYears": {
      "option": "1week" | "2weeks" | "3weeks" | "4weeks" | "alternating" | "All" | "Omit",
      "weeks": null,
      "reasoning": "quote"
    }
  },
  
  "holidays": {
    "mlk": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "presidentsDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "easter": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "mothersDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "memorialDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "fathersDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "julyFourth": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "laborDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "halloween": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" },
    "veteransDay": { "evenYears": "parent-a" | "parent-b" | "omit", "oddYears": "parent-a" | "parent-b" | "omit" }
  },
  
  "identifiedParties": {
    "parentA": { "name": "string or null", "role": "Mother" | "Father", "isCustodial": true },
    "parentB": { "name": "string or null", "role": "Mother" | "Father", "isCustodial": false }
  },
  
  "schoolCounty": "barrow" | "bibb" | "cobb" | "dekalb" | "forsyth" | "fulton" | "gwinnett" | "hall" | "jackson" | "newton" | "rockdale" | "walton" | null,
  
  "warnings": ["List provisions that couldn't be mapped or need manual review"]
}

PARSING RULES:

1. WEEKEND PATTERNS - READ CAREFULLY:
   FIRST: Look for a section stating something like "During the term of this parenting plan, the non-custodial parent shall have at minimum the following rights of parenting time."
   
   CRITICAL DISTINCTION - PAY CLOSE ATTENTION TO THE WORD "OTHER":
   - "every OTHER weekend" / "alternating weekends" / "alternate weekends" → "alternating-odd"
   - "every weekend" (WITHOUT the word "other") → "every"
   
   WARNING: "Every other weekend" is MUCH more common than "every weekend". 
   The word "OTHER" completely changes the meaning:
   - "Every weekend" = EVERY single weekend (pattern = "every")
   - "Every OTHER weekend" = alternating weekends, every 2 weeks (pattern = "alternating-odd")
   
   Be thorough and careful to look for the word "other" as the key differentiator.
   
   Other patterns:
   - "first and third weekends" → "first-third"
   - "second and fourth weekends" → "second-fourth"
   
   Note the start day (usually Friday) and end day (usually Sunday)

2. MIDWEEK VISITATION:
   - "Wednesday evening from 5pm to 8pm" → wednesday: { enabled: true, hours: 3 }
   - "overnight on Wednesday" → wednesday: { enabled: true, hours: 24 }

3. HOLIDAY ALTERNATING:
   - "Father has Thanksgiving in even years" → If Father is Parent B: evenYears: "parent-b"
   - "Mother's Day with Mother regardless of schedule" → Assign to whichever parent is Mother
   - "Father's Day with Father regardless of schedule" → Assign to whichever parent is Father

4. CHRISTMAS SPLITS:
   - "First half/second half" or "Christmas Eve/Christmas Day" splits → "Split"
   - Determine which parent gets first half based on year parity

5. SUMMER:
   - "Two weeks of uninterrupted time" → "2weeks"
   - "Four weeks" → "4weeks"
   - "Week on/week off during summer" → "alternating"
   - "Extended summer parenting time" → estimate weeks or use "4weeks"

6. SCHOOL COUNTY:
   - Look for school district mentions, county references, or addresses
   - If Gwinnett County Schools mentioned → "gwinnett"

7. DEFAULT TO "Omit":
   - If a provision is not mentioned at all, use "Omit"
   - Do not assume standard arrangements unless explicitly stated

Always include reasoning with direct quotes from the document to support each selection."""

ENHANCED_PARENTING_PLAN_PROMPT = """You are analyzing a Georgia parenting plan PDF. You will be given:
(1) extracted text from the parenting plan PDF, and
(2) the app's current form snapshot, including school-calendar-derived holidays and breaks (date ranges) and the current schedule selections.

Your job:

1. Extract Parent A (custodial parent) and Parent B (non-custodial parent exercising parenting time).

2. Identify every parenting plan provision that changes the start date, end date, exchange date, or time window of any holiday, school break, or vacation period relative to the school calendar.

3. Apply those provisions to the provided school-calendar date ranges to compute corrected date ranges for parenting time.

CRITICAL BREAK NAMING RULES (YOU MUST FOLLOW THESE EXACTLY):
- **Christmas Break** = ANY break in DECEMBER, regardless of what the document calls it. Even if the parenting plan says "Winter Break" for December, you MUST interpret it as "Christmas Break".
- **Winter Break** = ANY break in FEBRUARY (usually around Presidents Day). This is ALWAYS distinct from Christmas Break.
- **Fall Break** = ANY break or holiday in OCTOBER. Even if the document says "Teacher Workday", "Student Holiday", or "Fall Holiday" - if it's in October, treat it as Fall Break.
- **Thanksgiving Break** = Occurs in NOVEMBER around Thanksgiving Day.
- **Spring Break** = Occurs in MARCH or APRIL.

CHRISTMAS BREAK IS MANDATORY:
- Every school calendar has a December break. Christmas Break should NEVER be blank or "Omit" unless explicitly excluded by the parenting plan.
- If the form snapshot shows Christmas Break dates but the parenting plan is silent, still include the Christmas Break allocation (usually alternating or split).

Important rules:

- Do NOT invent new holidays or breaks. Only evaluate and correct the date fields provided in dateFields.

- If the parenting plan specifies times (for example 6:00 p.m.), still output corrected dates appropriate for a date-only UI by including any date that is covered by the plan's time window.

- Holiday and vacation "weekend inclusion" rules must be applied when the plan's language covers holidays and/or vacation periods, even if the school calendar starts on a Monday or ends on a Friday.

DATE CORRECTION CHAIN OF REASONING - CRITICAL (FOLLOW EXACTLY):

The school calendar dates represent STUDENT DAYS OFF (when students are not in school).
Parenting plan rules about "school is dismissed" and "day before school resumes" refer to dates OUTSIDE the school calendar break dates.

**UNDERSTANDING "SCHOOL IS DISMISSED" vs "SCHOOL RESUMES":**
- "School is dismissed" = the LAST school day BEFORE the break (students leave school that day, then break begins)
- "School resumes" = the FIRST school day AFTER the break (students return to school that day)
- Neither of these days is part of the break itself - they are school days on either side of the break

**HOW TO CALCULATE DISMISSAL AND RESUME DAYS:**
1. Look at the original break START date. Find the weekday. The dismissal day is the school day immediately BEFORE this date.
   - If break starts Monday, dismissal = prior Friday
   - If break starts Tuesday, dismissal = Monday (unless Monday is also off)
   - If break starts Saturday, dismissal = Friday

2. Look at the original break END date. Find the weekday. The resume day is the school day immediately AFTER this date.
   - If break ends Friday, resume = following Monday
   - If break ends Sunday, resume = following Monday
   - If break ends Wednesday, resume = Thursday

**APPLYING THE CORRECTIONS:**
- "Begins when school is dismissed" → corrected start = the dismissal day (BEFORE original start)
- "Ends the day before school resumes" → corrected end = the day BEFORE the resume day (AFTER original end)

**CONCRETE EXAMPLE - SPRING BREAK:**
- School calendar: Spring Break = April 6-10, 2026 (Mon-Fri, student days OFF)
- Parenting plan: "begins 6pm the day school is dismissed and ends 6pm the day before school resumes"
- Step 1: Break starts Mon Apr 6 → dismissal = Fri Apr 3
- Step 2: Break ends Fri Apr 10 → resume = Mon Apr 13 → day before resume = Sun Apr 12
- CORRECT OUTPUT: April 3 to April 12 (extended on BOTH ends)
- WRONG OUTPUT: April 3 to April 5 (this incorrectly SHORTENS the break - the AI calculated Apr 5 by going backward from Apr 6 instead of forward from Apr 10)

**COMMON ERROR TO AVOID:** Do not confuse "day before school resumes" with "day before break starts." The phrase "day before school resumes" refers to the day AFTER the break ends, not before the break begins. School resumes AFTER the break, not before it.

- Resolve conflicts using the plan's precedence language (holidays vs spring break vs summer, etc.) if stated.

Key rules to detect and apply:
- "Friday holiday includes following Sat/Sun" and "Monday holiday includes preceding Sat/Sun"
- "Begins at 6pm the day school is dismissed" = start on the school day BEFORE the break starts (use weekday calculation above)
- "Ends 6pm the day before school resumes" = end on the day BEFORE school resumes AFTER the break ends (use weekday calculation above)
- Thanksgiving-specific rules (e.g., "begins Wednesday before")
- Holiday weekend definitions that start Friday before a Monday holiday

REGULAR WEEKLY SCHEDULE - CRITICAL DISTINCTION:
When determining the regularWeeklySchedule pattern, look for a section stating something like "During the term of this parenting plan, the non-custodial parent shall have at minimum the following rights of parenting time."

PAY CLOSE ATTENTION TO THE WORD "OTHER":
- "every OTHER weekend" / "alternating weekends" / "alternate weekends" → pattern = "alternating-odd"
- "every weekend" (WITHOUT the word "other") → pattern = "every"

WARNING: "Every other weekend" is MUCH more common than "every weekend". The word "OTHER" completely changes the meaning:
- "Every weekend" = EVERY single weekend (pattern = "every")
- "Every OTHER weekend" = alternating weekends, every 2 weeks (pattern = "alternating-odd")

Be thorough and careful to look for the word "other" as the key differentiator.

Return JSON only in this schema:

{
  "parties": {
    "parentA": {"name": "string", "role": "Custodial"},
    "parentB": {"name": "string", "role": "Non-Custodial"},
    "primaryPhysicalCustodian": "Mother|Father|Joint|Unknown",
    "confidence": "high|medium|low",
    "notes": "string"
  },
  "rulesDetected": {
    "weekendDefinition": "string or null",
    "holidayWeekendRule": "string or null",
    "vacationStartRule": "string or null",
    "vacationEndRule": "string or null",
    "thanksgivingRule": "string or null",
    "winterBreakSplitRule": "string or null",
    "christmasSplitRule": "string or null",
    "schoolDayTimeWindowRule": "string or null",
    "precedenceRules": ["string"]
  },
  "dateCorrections": [
    {
      "label": "string",
      "startFieldId": "string",
      "endFieldId": "string",
      "exchangeFieldId": "string or null",
      "originalStartDate": "string or null",
      "originalEndDate": "string or null",
      "originalExchangeDate": "string or null",
      "correctedStartDate": "string or null",
      "correctedEndDate": "string or null",
      "correctedExchangeDate": "string or null",
      "reason": "string",
      "confidence": "high|medium|low"
    }
  ],
  "regularWeeklySchedule": {
    "pattern": "first-third|second-fourth|alternating-odd|alternating-even|every|Omit",
    "beginDay": "friday|thursday|saturday",
    "endDay": "sunday|monday",
    "reasoning": "string"
  },
  "recurringDaytimePeriods": {
    "frequency": "first-third|second-fourth|every|every-other|Omit",
    "everyOtherType": "odd|even|null",
    "days": {
      "monday": {"enabled": false, "hours": 0},
      "tuesday": {"enabled": false, "hours": 0},
      "wednesday": {"enabled": true, "hours": 4},
      "thursday": {"enabled": false, "hours": 0},
      "friday": {"enabled": false, "hours": 0},
      "saturday": {"enabled": false, "hours": 0},
      "sunday": {"enabled": false, "hours": 0}
    },
    "reasoning": "string"
  },
  "springBreak": {
    "evenYears": {"parent": "A|B|Omit", "reasoning": "string"},
    "oddYears": {"parent": "A|B|Omit", "reasoning": "string"}
  },
  "fallBreak": {
    "evenYears": {"parent": "A|B|Omit", "reasoning": "string"},
    "oddYears": {"parent": "A|B|Omit", "reasoning": "string"}
  },
  "thanksgivingBreak": {
    "evenYears": {"parent": "A|B|Split|Omit", "firstSplitParent": "A|B|null", "exchangeDate": "YYYY-MM-DD or null", "reasoning": "string"},
    "oddYears": {"parent": "A|B|Split|Omit", "firstSplitParent": "A|B|null", "exchangeDate": "YYYY-MM-DD or null", "reasoning": "string"}
  },
  "christmasBreak": {
    "evenYears": {"parent": "A|B|Split|Omit", "firstSplitParent": "A|B|null", "exchangeDate": "YYYY-MM-DD or null", "reasoning": "string"},
    "oddYears": {"parent": "A|B|Split|Omit", "firstSplitParent": "A|B|null", "exchangeDate": "YYYY-MM-DD or null", "reasoning": "string"}
  },
  "winterBreak": {
    "evenYears": {"parent": "A|B|Omit", "reasoning": "string"},
    "oddYears": {"parent": "A|B|Omit", "reasoning": "string"}
  },
  "holidays": {
    "mlk": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "presidentsDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "easter": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "mothersDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "memorialDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "fathersDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "fourthOfJuly": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "laborDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "halloween": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"},
    "veteransDay": {"evenYears": "A|B|omit", "oddYears": "A|B|omit"}
  },
  "summerSchedule": {
    "evenYears": {"option": "1week|2weeks|3weeks|4weeks|alternating|All|Omit", "reasoning": "string"},
    "oddYears": {"option": "1week|2weeks|3weeks|4weeks|alternating|All|Omit", "reasoning": "string"}
  },
  "shortSummary": "string (1-3 sentences)",
  "longSummary": "string (detailed explanation)",
  "confidence": "high|medium|low"
}

SPLIT BREAK FIELDS:
- When thanksgivingBreak or christmasBreak has parent="Split", you MUST also provide:
  - firstSplitParent: Which parent (A or B) gets the FIRST half of the break
  - exchangeDate: The date when custody exchanges from first parent to second parent (YYYY-MM-DD format)
- If the parenting plan specifies "first half to Mother" or "Christmas Eve to Father", map to A or B based on party identification.
- For Christmas splits, common exchange dates are December 25 or December 26 at noon.
- For Thanksgiving splits, exchange is often Thanksgiving Day itself.

In dateCorrections:
- Include an entry for every dateFields item where a change is needed.
- If no change is needed for an item, you may omit it from the array.
- Set corrected dates to the new values based on parenting plan rules.
- Provide a clear reason referencing the specific plan language that requires the adjustment.
"""

AUDIT_SYSTEM_PROMPT = """You are an expert Georgia family law attorney and legal drafting specialist conducting a comprehensive audit of a parenting plan document. Your role is to identify issues that could lead to conflict, confusion, or litigation, and to suggest precise revision language.

Analyze the document for the following categories:

## CATEGORY 1: NOVEL PROVISIONS AFFECTING PARENTING TIME

Identify any provisions that affect overnight or daytime parenting time but fall outside standard arrangements. Examples include:

RELIGIOUS/CULTURAL HOLIDAYS:
- Eid al-Fitr / Eid al-Adha
- Passover / Rosh Hashanah / Yom Kippur / Hanukkah
- Diwali / Holi
- Chinese New Year / Lunar New Year
- Orthodox Easter (if different from Western Easter)
- Good Friday
- Ash Wednesday
- Kwanzaa
- Three Kings Day / Epiphany
- Any saint's days or patron feast days

CUSTOM SCHEDULES:
- 2-2-3 rotation schedules
- 3-4-4-3 schedules
- 5-2-2-5 schedules
- Week-on/week-off during school year
- Schedules tied to work shifts (e.g., "when Father is off rotation")
- Distance-based modifications (e.g., different schedule if parent moves X miles)
- Age-based step-up provisions (schedule changes as child ages)
- School-year vs non-school-year differences beyond summer

SPECIAL OCCASIONS:
- Child's birthday
- Parents' birthdays
- Extended family events (grandparent birthdays, family reunions)
- Sibling visitation coordination
- Sports seasons or extracurricular schedules
- Teacher workdays / professional development days
- Weather-related school closures
- Half-days

TRAVEL & EXTENDED TIME:
- International travel provisions
- Notice requirements for vacation
- Passport possession and control
- Out-of-state travel restrictions
- Make-up time provisions

For each novel provision found, provide:
- The provision text (quoted)
- Estimated impact on annual overnight count
- Whether it's captured by the standard calendar tool
- Any potential conflicts with other provisions

## CATEGORY 2: AMBIGUITIES

Identify language that could reasonably be interpreted multiple ways:

TIMING AMBIGUITIES:
- "Weekend" without defined start/end times
- "Evening" or "afternoon" without specific hours
- "After school" when school dismissal varies
- "Holidays" without specifying observed dates vs calendar dates
- "Spring Break" without specifying whose calendar (school, county, state)
- "Summer" without defined start/end dates
- "Overnight" without defining minimum hours

ASSIGNMENT AMBIGUITIES:
- Provisions that don't clearly assign the child to one parent
- "Shared" time without specifying division
- "Flexible" or "as agreed" without default provisions
- References to schedules "to be determined"
- Provisions contingent on undefined conditions

PRIORITY AMBIGUITIES:
- Unclear which provision controls when holidays fall on regular parenting days
- Whether holiday time extends or replaces regular time
- Which parent's notice deadline applies when both have rights

DEFINITIONAL AMBIGUITIES:
- "Parent" vs "Father/Mother" used inconsistently
- "Child" when there are multiple children with different arrangements
- Geographic terms without clear boundaries
- "Reasonable" without objective standards

For each ambiguity, provide:
- The ambiguous text (quoted)
- Two or more reasonable interpretations
- Potential for conflict (high/medium/low)
- Suggested revision with precise language

## CATEGORY 3: DRAFTING ERRORS & CONFLICTS

Identify technical problems:

INTERNAL CONFLICTS:
- Provisions that contradict each other
- Math that doesn't add up (e.g., percentages exceeding 100%)
- Dates that create impossible schedules
- Overlapping exclusive time periods

REFERENCE ERRORS:
- References to non-existent paragraphs or exhibits
- Incorrect cross-references
- Orphaned definitions (defined but never used)
- Undefined terms used as if defined

TEMPORAL ERRORS:
- Provisions creating schedule gaps (child unassigned)
- Provisions creating double-assignment (child with both parents)
- Holiday dates that don't match actual calendar
- "Next" or "following" without clear antecedent

LEGAL/PROCEDURAL ISSUES:
- Provisions potentially unenforceable under Georgia law
- Missing required statutory language
- Inconsistency with referenced court orders
- Provisions that may conflict with OCGA § 19-9-3 or § 19-6-15

For each error, provide:
- The problematic text (quoted)
- Nature of the error
- Severity (critical/moderate/minor)
- Suggested correction

## CATEGORY 4: OMISSIONS

Identify common provisions that are missing:

COMMONLY OMITTED ITEMS:
- Right of First Refusal (and threshold hours)
- Transportation responsibilities and exchange location
- Communication provisions (phone/video calls)
- Method for resolving scheduling disputes
- Makeup time for missed parenting periods
- Illness protocols
- Childcare during parenting time
- Introduction of significant others
- Relocation notice requirements
- Modification procedures
- Electronic communication/social media provisions

GEORGIA-SPECIFIC OMISSIONS:
- Failure to address OCGA § 19-9-3 access provisions
- Missing language required by local court rules
- Parenting plan components required by standing orders

PRACTICAL OMISSIONS:
- School enrollment decisions
- Extracurricular activity decisions
- Medical decision-making during parenting time
- Emergency contact protocols
- Travel documentation (especially for international)

For each omission, provide:
- What is missing
- Potential consequences of the omission
- Recommended provision language

## CATEGORY 5: CLARITY IMPROVEMENT OPPORTUNITIES

Even if not technically ambiguous, identify provisions that could be clearer:

- Passive voice that obscures responsibility
- Complex sentences that could be simplified
- Provisions that would benefit from examples
- Places where a table or schedule format would be clearer
- Redundant language that could be consolidated
- Archaic legal language that could be modernized
- Provisions that should cross-reference each other but don't

---

OUTPUT FORMAT:

Return a JSON object with this structure:

{
  "documentSummary": {
    "custodialParent": "Mother" | "Father" | "Joint" | "Unclear",
    "childrenCount": number,
    "approximateDate": "date if identifiable",
    "courtCase": "case number if visible",
    "overallDraftingQuality": "Strong" | "Adequate" | "Needs Improvement" | "Significant Issues"
  },
  
  "novelProvisions": [
    {
      "id": "NP-1",
      "category": "Religious Holiday" | "Custom Schedule" | "Special Occasion" | "Travel" | "Other",
      "quotedText": "exact quote from document",
      "description": "plain language explanation",
      "estimatedOvernightImpact": "+/- X nights per year",
      "capturedByTool": false,
      "conflictRisk": "high" | "medium" | "low",
      "recommendations": "how to handle in calendar tool or suggested clarification"
    }
  ],
  
  "ambiguities": [
    {
      "id": "AMB-1",
      "type": "Timing" | "Assignment" | "Priority" | "Definitional",
      "quotedText": "exact quote",
      "interpretations": [
        "Interpretation A: ...",
        "Interpretation B: ..."
      ],
      "conflictPotential": "high" | "medium" | "low",
      "suggestedRevision": "The Father's weekend parenting time shall begin at 6:00 p.m. on Friday and end at 6:00 p.m. on Sunday."
    }
  ],
  
  "draftingErrors": [
    {
      "id": "ERR-1",
      "type": "Internal Conflict" | "Reference Error" | "Temporal Error" | "Legal Issue",
      "severity": "critical" | "moderate" | "minor",
      "quotedText": "exact quote(s)",
      "explanation": "what the problem is",
      "suggestedCorrection": "revised language"
    }
  ],
  
  "omissions": [
    {
      "id": "OM-1",
      "category": "Right of First Refusal" | "Transportation" | "Communication" | "Dispute Resolution" | "Makeup Time" | "Medical" | "Travel" | "Other",
      "description": "what is missing",
      "riskLevel": "high" | "medium" | "low",
      "consequences": "potential problems from this omission",
      "suggestedProvision": "complete suggested language to add"
    }
  ],
  
  "clarityImprovements": [
    {
      "id": "CLR-1",
      "quotedText": "current language",
      "issue": "why it could be clearer",
      "suggestedRevision": "improved language"
    }
  ],
  
  "executiveSummary": {
    "criticalIssuesCount": number,
    "totalFindingsCount": number,
    "topThreePriorities": [
      "Most important issue to address",
      "Second priority",
      "Third priority"
    ],
    "estimatedUncapturedOvernights": "X-Y nights per year not reflected in standard calendar tool",
    "overallAssessment": "2-3 sentence summary of document quality and main concerns"
  }
}"""


def analyze_for_audit(text):
    """Send extracted text to OpenAI for drafting audit analysis."""
    client = get_openai_client()
    if not client:
        logger.error("OpenAI client not initialized - missing environment variables")
        raise Exception("AI service is not configured. Please contact support.")
    
    try:
        logger.info("Starting OpenAI audit analysis request...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conduct a comprehensive drafting audit of this parenting plan document:\n\n{text}"}
            ],
            response_format={"type": "json_object"},
            max_tokens=8192,
            timeout=180
        )
        logger.info("OpenAI audit analysis completed successfully")
        
        result = response.choices[0].message.content or "{}"
        return json.loads(result)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI audit response as JSON: {str(e)}")
        raise Exception("AI returned invalid response format. Please try again.")
    except Exception as e:
        logger.error(f"OpenAI API error during audit: {str(e)}")
        raise Exception(f"Error analyzing document with AI: {str(e)}")


def extract_text_from_pdf(pdf_bytes):
    """Extract text from PDF, using OCR for scanned documents or garbled text."""
    extracted_text = ""
    is_scanned = False
    
    def is_text_garbled(text):
        """Check if extracted text appears garbled (many single-character alphabetic tokens)."""
        if not text or len(text) < 50:
            return True
        words = text.split()
        if not words:
            return True
        alpha_words = [w for w in words if w.isalpha()]
        if len(alpha_words) < 10:
            return False
        single_char_alpha = sum(1 for w in alpha_words if len(w) == 1)
        single_char_ratio = single_char_alpha / len(alpha_words) if alpha_words else 0
        avg_alpha_word_len = sum(len(w) for w in alpha_words) / len(alpha_words) if alpha_words else 0
        return single_char_ratio > 0.4 and avg_alpha_word_len < 2.0
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=3,
                    y_tolerance=3
                ) or ""
                
                if is_text_garbled(page_text):
                    words = page.extract_words(
                        x_tolerance=3,
                        y_tolerance=3,
                        keep_blank_chars=False
                    )
                    if words:
                        lines = {}
                        for word in words:
                            y_key = round(word['top'] / 10) * 10
                            if y_key not in lines:
                                lines[y_key] = []
                            lines[y_key].append((word['x0'], word['text']))
                        
                        page_text = ""
                        for y_key in sorted(lines.keys()):
                            line_words = sorted(lines[y_key], key=lambda w: w[0])
                            page_text += " ".join(w[1] for w in line_words) + "\n"
                
                extracted_text += page_text + "\n"
        
        if len(extracted_text.strip()) < 100 or is_text_garbled(extracted_text):
            is_scanned = True
            extracted_text = ""
            images = convert_from_bytes(pdf_bytes)
            for img in images:
                page_text = pytesseract.image_to_string(img)
                extracted_text += page_text + "\n"
    except Exception as e:
        raise Exception(f"Error extracting text from PDF: {str(e)}")
    
    return extracted_text.strip(), is_scanned


def extract_calendar_shading(pdf_bytes):
    """Extract colored/shaded cells from calendar PDFs to identify holidays."""
    shading_info = []
    month_names = ['january', 'february', 'march', 'april', 'may', 'june', 
                   'july', 'august', 'september', 'october', 'november', 'december']
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_width = pdf.pages[0].width if pdf.pages else 612
            
            for page_num, page in enumerate(pdf.pages):
                rects = page.rects or []
                chars = page.chars or []
                words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
                
                month_regions = []
                for word in words:
                    word_lower = word.get('text', '').lower().strip()
                    for month in month_names:
                        if month in word_lower:
                            is_left = word['x0'] < page_width / 2
                            x_start = 0 if is_left else page_width / 2
                            x_end = page_width / 2 if is_left else page_width
                            month_regions.append({
                                'name': month.capitalize(),
                                'x_start': x_start,
                                'x_end': x_end,
                                'y': word['top']
                            })
                
                digit_chars = [(c['x0'], c['top'], c.get('text', '')) for c in chars 
                               if c.get('text', '').strip().isdigit()]
                
                for rect in rects:
                    fill = rect.get('non_stroking_color')
                    if fill and fill != (1, 1, 1) and fill != (0, 0, 0):
                        x0, y0, x1, y1 = rect.get('x0', 0), rect.get('top', 0), rect.get('x1', 0), rect.get('bottom', 0)
                        width = x1 - x0
                        height = y1 - y0
                        
                        if 10 < width < 100 and 8 < height < 60:
                            color_name = 'unknown'
                            if isinstance(fill, tuple) and len(fill) >= 3:
                                r, g, b = fill[0], fill[1], fill[2]
                                if r > 0.7 and g > 0.7 and b < 0.6:
                                    color_name = 'yellow'
                                elif r < 0.5 and g > 0.5 and b < 0.5:
                                    color_name = 'green'
                                elif r < 0.6 and g < 0.6 and b > 0.6:
                                    color_name = 'blue'
                                elif r > 0.6 and g < 0.5 and b < 0.5:
                                    color_name = 'red'
                                elif 0.4 < r < 0.8 and 0.4 < g < 0.8 and 0.4 < b < 0.8:
                                    color_name = 'gray'
                            
                            chars_in_rect = []
                            for cx, cy, ch in digit_chars:
                                if x0 - 3 <= cx <= x1 + 3 and y0 - 3 <= cy <= y1 + 3:
                                    chars_in_rect.append((cx, ch))
                            
                            if chars_in_rect:
                                chars_in_rect.sort(key=lambda x: x[0])
                                day_num = ''.join(ch for _, ch in chars_in_rect)
                                
                                if day_num.isdigit() and 1 <= int(day_num) <= 31:
                                    rect_center_x = (x0 + x1) / 2
                                    month_context = None
                                    best_match_y = -1
                                    
                                    for region in month_regions:
                                        if region['x_start'] <= rect_center_x <= region['x_end']:
                                            if region['y'] < y0 and region['y'] > best_match_y:
                                                month_context = region['name']
                                                best_match_y = region['y']
                                    
                                    shading_info.append({
                                        'day': int(day_num),
                                        'month': month_context,
                                        'color': color_name,
                                        'position_y': round(y0)
                                    })
    except Exception as e:
        logger.warning(f"Could not extract shading info: {e}")
    
    return shading_info


def analyze_with_openai(text, form_snapshot=None):
    """Send extracted text to OpenAI for analysis."""
    import logging
    logger = logging.getLogger(__name__)
    
    client = get_openai_client()
    if not client:
        logger.error("OpenAI client not initialized - missing environment variables")
        raise Exception("AI service is not configured. Please contact support.")
    
    try:
        if form_snapshot:
            logger.info("Starting enhanced OpenAI analysis with form snapshot...")
            user_content = f"""Analyze this parenting plan document and extract the scheduling information.

PARENTING PLAN TEXT:
{text}

CURRENT FORM STATE (including school calendar dates):
{json.dumps(form_snapshot, indent=2)}

Apply any date correction rules from the parenting plan to the dates provided in dateFields."""
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": ENHANCED_PARENTING_PLAN_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                max_tokens=8192,
                timeout=180
            )
        else:
            logger.info("Starting OpenAI analysis request...")
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze this parenting plan document and extract the scheduling information:\n\n{text}"}
                ],
                response_format={"type": "json_object"},
                max_tokens=4096,
                timeout=120
            )
        logger.info("OpenAI analysis completed successfully")
        
        result = response.choices[0].message.content or "{}"
        return json.loads(result)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {str(e)}")
        raise Exception("AI returned invalid response format. Please try again.")
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise Exception(f"Error analyzing document with AI: {str(e)}")


@main.route('/analyze_document', methods=['POST'])
def analyze_document():
    """Analyze an uploaded parenting plan PDF document."""
    step = "init"
    try:
        step = "auth_check"
        # Premium Attorney Plan exclusive feature (also available to government users)
        if not current_user.is_authenticated:
            return jsonify({'error': 'The Parenting Plan Analyzer is a Premium Attorney Plan exclusive feature. Please subscribe to access this feature.', 'premium_required': True}), 403
        
        if current_user.subscription_type not in ['paid', 'government']:
            return jsonify({'error': 'The Parenting Plan Analyzer is a Premium Attorney Plan exclusive feature. Please subscribe to access this feature.', 'premium_required': True}), 403
        
        step = "pdfplumber_check"
        if not pdfplumber:
            return jsonify({'error': 'PDF processing is temporarily unavailable. Please try again later.'}), 503
        
        step = "file_check"
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        if file.filename == '' or file.filename is None:
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are accepted'}), 400
        
        step = "read_file"
        pdf_bytes = file.read()
        
        if len(pdf_bytes) > 10 * 1024 * 1024:
            return jsonify({'error': 'File size exceeds 10MB limit'}), 400
        
        step = "extract_text"
        extracted_text, is_scanned = extract_text_from_pdf(pdf_bytes)
        
        if len(extracted_text) < 50:
            return jsonify({'error': 'Could not extract sufficient text from the document. Please ensure the PDF contains readable text.'}), 400
        
        step = "parse_form_snapshot"
        form_snapshot = None
        form_snapshot_str = request.form.get('formSnapshot')
        if form_snapshot_str:
            try:
                form_snapshot = json.loads(form_snapshot_str)
                logger.info(f"Received form snapshot with {len(form_snapshot.get('dateFields', []))} date fields")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse form snapshot: {e}")
        
        step = "openai_analysis"
        analysis_result = analyze_with_openai(extracted_text, form_snapshot)
        
        step = "build_response"
        analysis_result['_meta'] = {
            'wasScanned': is_scanned,
            'textLength': len(extracted_text),
            'hadFormSnapshot': form_snapshot is not None,
            'dateFieldsCount': len(form_snapshot.get('dateFields', [])) if form_snapshot else 0
        }
        
        return jsonify(analysis_result)
    
    except Exception as e:
        logger.error(f"Error in analyze_document at step '{step}': {str(e)}")
        return jsonify({'error': str(e), 'failed_at_step': step}), 500


@main.route('/generate_audit_report', methods=['POST'])
@login_required
def generate_audit_report():
    """Generate a drafting audit report for an uploaded parenting plan PDF."""
    if not pdfplumber:
        return jsonify({'error': 'PDF processing is temporarily unavailable. Please try again later.'}), 503
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if file.filename == '' or file.filename is None:
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are accepted'}), 400
    
    try:
        pdf_bytes = file.read()
        
        if len(pdf_bytes) > 10 * 1024 * 1024:
            return jsonify({'error': 'File size exceeds 10MB limit'}), 400
        
        extracted_text, is_scanned = extract_text_from_pdf(pdf_bytes)
        
        if len(extracted_text) < 50:
            return jsonify({'error': 'Could not extract sufficient text from the document. Please ensure the PDF contains readable text.'}), 400
        
        audit_result = analyze_for_audit(extracted_text)
        
        audit_result['_meta'] = {
            'wasScanned': is_scanned,
            'textLength': len(extracted_text),
            'generatedAt': __import__('datetime').datetime.now().isoformat()
        }
        
        return jsonify(audit_result)
    
    except Exception as e:
        logger.error(f"Error in generate_audit_report: {str(e)}")
        return jsonify({'error': str(e)}), 500


SCHOOL_CALENDAR_IMAGE_ANALYSIS_PROMPT = """You are an expert at analyzing school calendar images. Your task is to extract ONLY dates that are VISUALLY SHADED/COLORED on the calendar grid.

## CRITICAL RULE - SHADING VERIFICATION:
**A date should ONLY be extracted if the actual calendar cell for that date has visible shading/color fill.**
- WHITE/unshaded cells = students ARE in school = DO NOT EXTRACT
- COLORED/shaded cells (gray, orange, yellow, blue) = students may be off = CHECK LEGEND
- If a holiday is mentioned in text but the cell is WHITE, DO NOT extract it
- Saturday/Sunday should NOT be included in break ranges unless specifically shaded

## STEP 1: FIND AND READ THE COLOR KEY/LEGEND
1. Locate the color legend (usually at bottom of calendar)
2. Read EXACTLY what each color means
3. Identify which colors mean "students do not report" or "schools closed"

## STEP 2: SCAN EACH MONTH'S GRID FOR SHADED CELLS
For each month (July through June):
1. Look at EACH numbered date cell
2. Identify cells that have a colored BACKGROUND (not white)
3. Note the color of each shaded cell
4. Only proceed with dates that are actually shaded

## STEP 3: VERIFY SHADING BEFORE EXTRACTING
For each date range you want to extract:
1. VISUALLY CONFIRM each individual date cell is shaded
2. If a text annotation says "22-26" but day 27 is WHITE, the range ends at 26
3. Weekends (Sat/Sun) should NOT extend ranges unless they are also shaded
4. Federal holidays like Columbus Day - check if the cell is actually shaded

## STEP 4: READ TEXT ANNOTATIONS FOR LABELS
Use text annotations below each month for accurate labels and date ranges, but ONLY for dates you verified are shaded.

## OUTPUT FORMAT (return valid JSON):
{
  "success": true,
  "schoolName": "Name of the school/district from the calendar",
  "schoolYear": "2027-2028",
  "colorLegend": [
    {"color": "Gray", "meaning": "Holiday/Break - Schools Closed"},
    {"color": "Orange", "meaning": "Teachers' Workday - Students do not report"}
  ],
  "rawDates": [
    {
      "date": "YYYY-MM-DD",
      "endDate": "YYYY-MM-DD or null if single day",
      "label": "Label from calendar text",
      "category": "holiday|break|teacher_day|student_holiday|other",
      "isStudentDayOff": true,
      "colorUsed": "The actual color of this cell (gray, orange, yellow, white)",
      "shadingVerified": true,
      "month": "November"
    }
  ],
  "excludedDates": [
    {"date": "2027-10-11", "reason": "Columbus Day - cell is WHITE/unshaded"},
    {"date": "2027-11-27", "reason": "Saturday - cell is WHITE, not part of break"}
  ],
  "confidence": "high|medium|low"
}

## RULES:
- ONLY extract dates where the calendar cell is VISUALLY SHADED (not white)
- Do NOT include holidays that are only mentioned in text but have white cells
- Weekends should NOT extend break ranges unless they are shaded
- If you see Columbus Day/Indigenous Peoples Day in the legend but the Oct 11 cell is WHITE, do NOT include it
- Early Release days = students ARE in school (do not mark as day off)

## GEORGIA-SPECIFIC CONVENTIONS (apply these to Georgia school calendars):
- December breaks = "Christmas Break" (even if labeled "Winter Break")
- February breaks = "Winter Break" (this is the ONLY proper Winter Break in Georgia)
- If Presidents Day (Feb) is adjacent to other days off in February, label all as "Winter Break"
- Thanksgiving Break is in late November (typically week of Thanksgiving)
- If shading extends into January (Jan 1-3), those are part of Christmas Break

## COLOR PATTERN GUIDANCE:
- GRAY/DARK shading typically = Holiday/Break - Schools Closed (Thanksgiving, Christmas Break, etc.)
- ORANGE/LIGHT shading typically = Teachers' Workday - Students do not report
- YELLOW with border typically = Virtual/Independent Learning Day - Students do not report
- Look at EVERY month carefully - Thanksgiving (Nov), Christmas (Dec-Jan), Winter Break (Feb) are often gray
"""

SCHOOL_CALENDAR_RAW_EXTRACTION_PROMPT = """You are an expert at parsing school calendar documents. Your task is to extract EVERY date that is marked as a day off for students.

EXTRACT ALL OF THE FOLLOWING DATE TYPES:
- Holiday (e.g., Labor Day, MLK Day, Memorial Day, Independence Day, Veterans Day)
- Student Holiday / Student Day Off
- Teacher Planning Day / Teacher Workday / Professional Development
- Break (Fall Break, Thanksgiving Break, Winter Break, Spring Break, etc.)
- Early Release days (students are still in school, but note them)
- Any date that is shaded, highlighted, colored, or otherwise visually marked as special

For EACH date or date range you find, output an entry in a JSON array. Use this exact format:

{
  "success": true,
  "schoolName": "Name of the school/district",
  "schoolYear": "2025-2026" or similar,
  "rawDates": [
    {
      "date": "YYYY-MM-DD",
      "endDate": "YYYY-MM-DD or null if single day",
      "label": "Exact text label from the calendar (e.g., 'Teacher Planning Day', 'Winter Break', 'Student Holiday')",
      "category": "holiday|break|teacher_day|student_holiday|early_release|other",
      "isStudentDayOff": true or false,
      "visualIndicator": "Description of any visual marking (e.g., 'blue shading', 'green background', 'bold border', 'none')",
      "month": "January|February|...|December",
      "notes": "Any additional context"
    }
  ],
  "legendInfo": "Description of any legend or color key found in the calendar (e.g., 'Blue = Student/Teacher Holiday, Green = Teacher Workday')",
  "confidence": "high|medium|low"
}

CRITICAL EXTRACTION RULES:
1. Extract EVERY marked date - do not skip any dates that have visual indicators
2. Pay attention to color legends - calendars often use colors to denote different day types
3. Look at the margins/sides of each month - they often list holidays with dates
4. If a date range spans into the next month, include the full range (e.g., Dec 22 - Jan 2)
5. Extract Teacher Planning Days and Student Holidays separately even if they're adjacent to breaks
6. Note the visual indicator for each date (shading color, highlighting, etc.)
7. CRITICAL: If "Student Holiday" appears ANYWHERE in the label or nearby text (including in parentheses, on adjacent lines, or in the same entry), set isStudentDayOff to TRUE
8. Example: "Teacher Planning/Staff Development (Student Holiday)" = isStudentDayOff: true
9. Example: "Teacher Planning/Staff Development [#8] (Student Holiday)" = isStudentDayOff: true
10. KEY PRINCIPLE: A break ends on the last day BEFORE school resumes for students. Any "Teacher Planning Day", "Staff Development Day", or similar day marked as "Student Holiday" that immediately follows a break MUST be extracted with isStudentDayOff: true - these extend the break. This applies to ALL breaks (Fall Break, Thanksgiving, Christmas, Spring Break, etc.), not just specific ones.

CHRISTMAS BREAK EXTENSION - CRITICAL:
11. **January dates after Christmas/Winter Break are extremely important.** Many school calendars have "Teacher Planning/Staff Development" days in early January that are also "(Student Holiday)" - these MUST be extracted with isStudentDayOff: true.
12. Example from Gwinnett County: "Winter Break" ends Jan 1, then "Teacher Planning/Staff Development [#8-9] (Student Holiday)" on Jan 2 = Jan 2 must have isStudentDayOff: true. This extends Christmas Break to Jan 2.
13. When parsing January entries, look carefully for "(Student Holiday)" text even if it appears on a separate line from "Teacher Planning" - they belong together.
14. If the calendar shows shading/highlighting on January dates immediately after the break, include them with isStudentDayOff: true.

VISUAL INDICATOR DETECTION:
- Blue/grey shading often means student day off
- Green shading often means teacher workday/planning day
- Bold borders or different colors indicate special dates
- If ANY visual marking exists on a date, it should be extracted

EARLY RELEASE DAYS - CRITICAL:
15. **Early Release days are NOT student days off.** Students are still in school, just dismissed early.
16. Early Release days must ALWAYS have isStudentDayOff: false and category: "early_release"
17. Early Release days should NEVER be merged with adjacent breaks. Example: Dec 17-19 "Early Release for High School Exams" is separate from Dec 22-31 "Winter Break (School Holidays)"
18. If a school calendar shows "Early Release" on certain days before a break, those are NOT part of the break.

DATE RANGE BOUNDARIES - CRITICAL:
19. **Only use the hyphen-bound date range from the label.** If the text says "6-10 Spring Break", the dates are April 6-10, NOT any later numbers that may appear in adjacent text.
20. Do NOT extend date ranges by including unrelated numbers from nearby entries. Example: "6-10 Spring Break (School Holidays) ... 13 Students Return" means Spring Break is April 6-10, NOT April 6-13.
21. When a date range is explicitly stated with a hyphen (e.g., "22-31", "6-10", "9-13"), use EXACTLY those start and end days. Do not extend beyond the stated range.
22. If shading shows specific days (e.g., 6, 7, 8, 9, 10 shaded), use ONLY those shaded days as the date range.

EXCLUDE THESE FROM OUTPUT (STUDENTS ARE STILL IN SCHOOL):
- Digital Learning Days (students are still in school, just learning remotely)
- Independent Learning Days / IL Days (students are learning remotely, NOT a day off)
- Professional Learning Days / PL Days when students are doing independent learning
- Virtual Learning Days (students are attending school virtually)
- Pre-planning days BEFORE the first day of school (these are teacher-only workdays)
- Administrative meetings before school starts
- Any day marked with green shading that indicates "Independent Learning" or "PL Day" per the legend

CALENDAR MARKERS TO EXCLUDE (THESE ARE SCHOOL DAYS, NOT DAYS OFF):
23. **"End of Nine Weeks"** or "End of 1st/2nd/3rd/4th Nine Weeks" - These are just grading period markers, NOT student days off
24. **"First Day of School"** - This is a regular school day
25. **"Last Day of School"** - This is a regular school day (students attend)
26. **"Last Day of Semester"** or "End of Semester" - These are grading period markers, NOT days off
27. **"Report Card Day"** or "Progress Report" markers - These are informational only
28. Do NOT extract these dates as holidays or breaks. They mark the beginning/end of periods but students ARE in school on these days.
29. If a date has BOTH a marker (like "End of Nine Weeks") AND a day off label (like "Teacher Work Day"), only extract if the day off portion indicates students are out.

OUTPUT ALL STUDENT DAYS OFF - even if they seem redundant. The merge logic will be applied separately.
"""

SCHOOL_CALENDAR_SYSTEM_PROMPT = """You are an expert at parsing school calendar documents. Your task is to extract all holiday and break dates from the school calendar.

For each holiday/break, extract:
1. The name of the holiday or break (using STANDARDIZED names below)
2. The start date (when students are off)
3. The end date (last day off before returning to school)
4. Whether this is a standard holiday or if it appears to be omitted/not observed by this school district

Return a JSON object with the following structure:
{
  "success": true,
  "schoolName": "Name of the school/district if found",
  "schoolYear": "2024-2025" or similar,
  "holidays": [
    {
      "name": "Holiday name",
      "startDate": "YYYY-MM-DD",
      "endDate": "YYYY-MM-DD",
      "isOmitted": false,
      "notes": "Any additional notes about this holiday"
    }
  ],
  "omittedHolidays": ["List of standard holidays that appear to NOT be observed or are missing from this calendar"],
  "confidence": "high" | "medium" | "low",
  "notes": "Any additional observations about the calendar"
}

CRITICAL BREAK NAMING RULES (YOU MUST FOLLOW THESE EXACTLY):
1. **Christmas Break** = ANY break in DECEMBER, regardless of what the school calls it. Even if the school calendar says "Winter Break" for December, you MUST label it "Christmas Break" in your output.
2. **Winter Break** = ANY break in FEBRUARY (usually around Presidents Day). This is ALWAYS distinct from Christmas Break.
3. **Fall Break** = ANY holiday, student day off, or teacher workday in OCTOBER. Even if labeled "Teacher Workday", "Student Holiday", "Fall Holiday", or anything else - if it's in October, call it "Fall Break".
4. **Thanksgiving Break** = Occurs in NOVEMBER around Thanksgiving Day.
5. **Spring Break** = Occurs in MARCH or APRIL.

MERGING CONSECUTIVE BREAKS:
- If there is a holiday on Friday AND a student holiday or teacher workday on the following Monday, merge them into ONE continuous break.
- Example: "Professional Development Day" on Friday Oct 4 + "Student Holiday" on Monday Oct 7 = one "Fall Break" from Oct 4-7 (including the weekend).
- When a break ends on the last day of a month AND another break starts on the first day of the following month, merge them into ONE continuous break.
- Example: Christmas Break ending December 31 + New Year's Day January 1 = one continuous "Christmas Break" ending January 1 (or later if more days off follow).
- Always merge adjacent/consecutive days off into a single break entry, even across month boundaries.

APPENDING ADJACENT DAYS TO BREAKS:
- If a "Teacher Planning Day", "Student Holiday", "Teacher Workday", "Professional Development", or any similarly-named day off is CONSECUTIVE to an existing break, APPEND it to that break.
- This applies even when a break ends on Friday and the extra day(s) fall on the following Monday (or Tuesday after a Monday holiday).
- Example: Spring Break ends Friday March 28, Teacher Planning Day on Monday March 31 = extend Spring Break to end March 31.
- Example: Thanksgiving Break ends Friday Nov 29, Student Holiday on Monday Dec 2 = extend Thanksgiving Break to end Dec 2.

CHRISTMAS BREAK EXTENSION INTO JANUARY - CRITICAL:
- Christmas Break MUST include any adjacent January student holidays immediately following the break.
- Example: If "Winter Break (School Holidays)" ends Jan 1, and "Teacher Planning/Staff Development (Student Holiday)" is on Jan 2, then Christmas Break should be Dec 22 - Jan 2 (NOT Dec 22 - Jan 1).
- Look for "(Student Holiday)" notation on January dates even if it appears on a separate line or in parentheses - these days extend the Christmas Break.
- This is the most common error: failing to append January 2nd or 3rd student holidays to Christmas Break.

VISUAL CALENDAR INDICATORS:
- Pay close attention to dates that are SHADED with a color (not plain white), have BOLD BORDERS, are HIGHLIGHTED, or otherwise visually marked.
- These visual indicators often denote days off that should be included in breaks.
- If you see a colored/highlighted date adjacent to or near a break, verify whether it represents a day off that should be merged into that break.
- Common visual patterns: grey shading for student holidays, colored backgrounds for breaks, bold outlines for special days.

IMPORTANT - CHRISTMAS BREAK IS NEVER MISSING:
- Every school has a December break for Christmas/New Year. If you don't find it explicitly, look for "Winter Break" or "Holiday Break" in December and rename it to "Christmas Break".
- Christmas Break should NEVER appear in omittedHolidays.

Important guidelines:
- Use YYYY-MM-DD format for all dates
- For weekend holidays (like MLK Day), include the full weekend (Friday through Monday)
- For multi-week breaks, include the full range
- If a standard holiday is not mentioned, add it to omittedHolidays
- Standard holidays to look for: MLK Day, Presidents Day, Spring Break, Easter, Memorial Day, Labor Day, Fall Break, Veterans Day, Thanksgiving Break, Christmas Break, Winter Break
- If dates are ambiguous or unclear, set confidence to "low" or "medium"
"""


def analyze_school_calendar_with_openai(text):
    """Send extracted school calendar text to OpenAI for analysis."""
    try:
        client = get_openai_client()
    except Exception as e:
        logger.error(f"Failed to get OpenAI client: {e}")
        raise Exception(f"AI service initialization failed: {str(e)}")
    
    if not client:
        in_prod = is_production_environment()
        has_user_key = bool(os.environ.get("OPENAI_API_KEY", ""))
        logger.error(f"OpenAI client not initialized - Production: {in_prod}, Has OPENAI_API_KEY: {has_user_key}")
        if in_prod and not has_user_key:
            raise Exception("AI service requires OPENAI_API_KEY to be configured for production. Please add your OpenAI API key in the Secrets tab.")
        raise Exception("AI service is not configured. Please contact support.")
    
    try:
        logger.info("Starting OpenAI school calendar analysis request...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCHOOL_CALENDAR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract all holiday and break dates from this school calendar:\n\n{text}"}
            ],
            response_format={"type": "json_object"},
            max_tokens=4096,
            timeout=120
        )
        logger.info("OpenAI school calendar analysis completed successfully")
        
        result = response.choices[0].message.content or "{}"
        return json.loads(result)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI school calendar response as JSON: {str(e)}")
        raise Exception("AI returned invalid response format. Please try again.")
    except Exception as e:
        logger.error(f"OpenAI API error during school calendar analysis: {str(e)}")
        raise Exception(f"Error analyzing school calendar with AI: {str(e)}")


SCHOOL_CALENDAR_OCR_INTERPRETATION_PROMPT = """You are an expert at interpreting extracted text from school calendar images. 
The user will provide OCR-extracted text from a school calendar. Your task is to identify ALL dates when students do not attend school.

## CRITICAL: EXTRACT NUMBERS EXACTLY AS WRITTEN
When you see a date range like "5-8", extract EXACTLY 5 and 8, NOT 5 and 11 or any other numbers.
DO NOT GUESS OR INFER dates - use ONLY the numbers written in the OCR text.

WRONG: "5-8 - Fall Break" → Oct 5-11 (DO NOT DO THIS)
RIGHT: "5-8 - Fall Break" → Oct 5-8 (EXACT MATCH)

## EXTRACT ALL STUDENT DAYS OFF INCLUDING TEACHER WORKDAYS
Teacher Workdays / Professional Development days where "Students do not report" ARE student days off.
Example: "4 - Teachers' Virtual Workday" means Oct 4 is a student day off - INCLUDE IT.

## DATE EXTRACTION RULES:
1. MATCH TEXT EXACTLY - If the text says "5-8", use 5 and 8, NOT other numbers
2. INCLUDE teacher workdays/planning days as student days off
3. Determine the MONTH from context (which month section the text appears under)
4. Determine the YEAR from school year (2027-2028 means Jul-Dec=2027, Jan-Jun=2028)

## EXAMPLE EXTRACTIONS FOR DEKALB COUNTY 2027-2028:
- "4 - Teachers' Virtual Workday" under OCTOBER = Oct 4 (isStudentDayOff: true)
- "5-8 - Fall Break" under OCTOBER = Oct 5-8 (NOT Oct 5-11)
- "22-26 - Thanksgiving Break" under NOVEMBER = Nov 22-26 (NOT Nov 22-27)
- "20-31 - Winter Break" under DECEMBER = Dec 20-31 (label as Christmas Break)
- "3 - Post/Pre-Planning Day" under JANUARY = Jan 3 (isStudentDayOff: true)
- "17 - Dr. Martin Luther King Jr Day" under JANUARY = Jan 17
- "21 - Presidents Day" under FEBRUARY = Feb 21
- "22-25 - February Break" under FEBRUARY = Feb 22-25

## OUTPUT FORMAT (return valid JSON):
{
  "success": true,
  "schoolName": "Name from the calendar",
  "schoolYear": "2027-2028",
  "rawDates": [
    {
      "date": "YYYY-MM-DD",
      "endDate": "YYYY-MM-DD or null if single day",
      "label": "Label from calendar",
      "category": "holiday|break|teacher_day|student_holiday|other",
      "isStudentDayOff": true,
      "notes": "Include 'students do not report' if teacher workday",
      "month": "November",
      "textSource": "The EXACT text from calendar (e.g., '22-26 - Thanksgiving Break')"
    }
  ],
  "confidence": "high|medium|low"
}

IMPORTANT: For teacher workdays, set category="teacher_day", isStudentDayOff=true, and notes="students do not report".

## GEORGIA NAMING CONVENTIONS:
- December breaks = "Christmas Break" (even if text says "Winter Break")
- February breaks = "Winter Break" (even if text says "February Break")
- Merge Presidents Day (Feb 21) with February Break (Feb 22-25) into one Winter Break entry

## WHAT TO EXCLUDE:
- Weekends (Saturday/Sunday) unless specifically listed as part of a break
- Federal holidays NOT listed in the calendar text
- Early Release days (students ARE in school)
"""


def extract_text_from_calendar_image_ocr(image_bytes):
    """
    Use OCR (Tesseract) to extract ALL text from a calendar image.
    Returns the raw extracted text for AI interpretation.
    """
    if not pytesseract or not Image or not cv2 or not np:
        raise Exception("OCR dependencies not available. Please ensure pytesseract, PIL, cv2, and numpy are installed.")
    
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise Exception("Failed to decode image")
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        
        thresh = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        pil_image = Image.fromarray(thresh)
        
        custom_config = r'--oem 3 --psm 6'
        extracted_text = pytesseract.image_to_string(pil_image, config=custom_config)
        
        logger.info(f"OCR extracted {len(extracted_text)} characters from calendar image")
        logger.debug(f"OCR text preview: {extracted_text[:500]}...")
        
        return extracted_text
        
    except Exception as e:
        logger.error(f"OCR extraction failed: {str(e)}")
        raise Exception(f"Failed to extract text from calendar image: {str(e)}")


def analyze_calendar_with_ocr(image_bytes, filename="calendar.png"):
    """
    Analyze a calendar image using OCR + AI text interpretation.
    This is more accurate than Vision API for date extraction because:
    1. OCR reliably extracts text annotations
    2. AI is excellent at interpreting extracted text
    """
    try:
        extracted_text = extract_text_from_calendar_image_ocr(image_bytes)
        
        if not extracted_text or len(extracted_text.strip()) < 50:
            logger.warning(f"OCR extracted minimal text ({len(extracted_text)} chars), falling back to Vision")
            return None
        
        client = get_openai_client()
        if not client:
            raise Exception("AI service is not configured.")
        
        logger.info("Starting AI interpretation of OCR-extracted calendar text...")
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCHOOL_CALENDAR_OCR_INTERPRETATION_PROMPT},
                {"role": "user", "content": f"Interpret this OCR-extracted text from a school calendar and return JSON with all student days off:\n\n{extracted_text}"}
            ],
            response_format={"type": "json_object"},
            max_tokens=8192,
            timeout=120
        )
        
        logger.info("AI interpretation of OCR text completed successfully")
        
        result = response.choices[0].message.content or "{}"
        parsed_result = json.loads(result)
        
        parsed_result['extractionMethod'] = 'ocr_plus_ai'
        parsed_result['ocrTextLength'] = len(extracted_text)
        
        return parsed_result
        
    except Exception as e:
        logger.error(f"OCR+AI calendar analysis failed: {str(e)}")
        return None


def analyze_calendar_image_with_vision(image_bytes, filename="calendar.png"):
    """
    Analyze a calendar IMAGE using GPT-4o Vision capabilities.
    This function handles PNG, JPG, JPEG image files directly.
    """
    import base64
    
    try:
        client = get_openai_client()
    except Exception as e:
        logger.error(f"Failed to get OpenAI client: {e}")
        raise Exception(f"AI service initialization failed: {str(e)}")
    
    if not client:
        in_prod = is_production_environment()
        has_user_key = bool(os.environ.get("OPENAI_API_KEY", ""))
        logger.error(f"OpenAI client not initialized - Production: {in_prod}, Has OPENAI_API_KEY: {has_user_key}")
        if in_prod and not has_user_key:
            raise Exception("AI service requires OPENAI_API_KEY to be configured for production. Please add your OpenAI API key in the Secrets tab.")
        raise Exception("AI service is not configured. Please contact support.")
    
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        ext = filename.lower().split('.')[-1]
        if ext in ['jpg', 'jpeg']:
            media_type = 'image/jpeg'
        elif ext == 'png':
            media_type = 'image/png'
        elif ext == 'gif':
            media_type = 'image/gif'
        elif ext == 'webp':
            media_type = 'image/webp'
        else:
            media_type = 'image/png'
        
        logger.info(f"Starting GPT-4o Vision analysis of calendar image ({len(image_bytes)} bytes, {media_type})...")
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCHOOL_CALENDAR_IMAGE_ANALYSIS_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this school calendar image. CRITICAL: Only extract dates where the calendar cell is ACTUALLY SHADED with a color (gray, orange, yellow, etc.) - do NOT extract dates that are mentioned in text but have WHITE/unshaded cells. For each month, visually check which specific date cells have colored backgrounds. Weekends (Sat/Sun) should NOT extend break ranges unless they are also shaded. Columbus Day and similar holidays - verify the cell is shaded before including. Return JSON with only verified shaded dates."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=8192,
            timeout=180
        )
        
        logger.info("GPT-4o Vision calendar image analysis completed successfully")
        
        result = response.choices[0].message.content or "{}"
        return json.loads(result)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI vision response as JSON: {str(e)}")
        raise Exception("AI returned invalid response format. Please try again.")
    except Exception as e:
        logger.error(f"OpenAI Vision API error during calendar image analysis: {str(e)}")
        raise Exception(f"Error analyzing calendar image with AI: {str(e)}")


def extract_raw_calendar_dates(text):
    """
    Pass 1: Extract all raw dates from school calendar using AI.
    Returns raw date entries with labels and visual indicators.
    """
    try:
        client = get_openai_client()
    except Exception as e:
        logger.error(f"Failed to get OpenAI client: {e}")
        raise Exception(f"AI service initialization failed: {str(e)}")
    
    if not client:
        raise Exception("AI service is not configured.")
    
    try:
        logger.info("Starting raw date extraction from school calendar...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCHOOL_CALENDAR_RAW_EXTRACTION_PROMPT},
                {"role": "user", "content": f"Extract ALL marked dates from this school calendar. Include every date with visual indicators (shading, colors, highlighting):\n\n{text}"}
            ],
            response_format={"type": "json_object"},
            max_tokens=8192,
            timeout=120
        )
        logger.info("Raw date extraction completed successfully")
        
        result = response.choices[0].message.content or "{}"
        return json.loads(result)
    except Exception as e:
        logger.error(f"Error extracting raw dates: {str(e)}")
        raise Exception(f"Error extracting dates: {str(e)}")


def merge_and_normalize_breaks(raw_result):
    """
    Pass 2: Apply Python-based deterministic merge logic to raw dates.
    Merges adjacent dates, applies naming conventions, handles month boundaries.
    """
    from datetime import datetime, timedelta
    
    if not raw_result.get('rawDates'):
        return {
            'success': True,
            'schoolName': raw_result.get('schoolName', ''),
            'schoolYear': raw_result.get('schoolYear', ''),
            'holidays': [],
            'omittedHolidays': [],
            'confidence': raw_result.get('confidence', 'low'),
            'notes': 'No dates found in calendar'
        }
    
    def parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except:
            return None
    
    def is_adjacent(date1, date2):
        """Check if two dates are adjacent (including weekends)."""
        if not date1 or not date2:
            return False
        diff = abs((date2 - date1).days)
        if diff <= 1:
            return True
        if diff <= 3:
            d1_weekday = date1.weekday()
            d2_weekday = date2.weekday()
            if d1_weekday == 4 and d2_weekday == 0:
                return True
            if d1_weekday == 0 and d2_weekday == 4:
                return True
        return False
    
    def get_break_name(month, label, is_multi_day=False):
        """Normalize break name based on label content FIRST, then month as fallback for multi-day breaks."""
        label_lower = label.lower() if label else ''
        
        if 'mlk' in label_lower or 'martin luther' in label_lower or 'king' in label_lower:
            return 'MLK Day'
        if 'president' in label_lower:
            return 'Presidents Day'
        if 'memorial' in label_lower:
            return 'Memorial Day'
        if 'labor' in label_lower:
            return 'Labor Day'
        if 'veteran' in label_lower:
            return 'Veterans Day'
        if 'easter' in label_lower:
            return 'Easter'
        if 'independence' in label_lower or 'july 4' in label_lower or '4th of july' in label_lower:
            return 'Independence Day'
        if 'thanksgiving' in label_lower or 'thank' in label_lower:
            return 'Thanksgiving Break'
        if 'christmas' in label_lower:
            return 'Christmas Break'
        if 'spring' in label_lower and 'break' in label_lower:
            return 'Spring Break'
        if 'fall' in label_lower and 'break' in label_lower:
            return 'Fall Break'
        if 'winter' in label_lower and 'break' in label_lower:
            if month == 12:
                return 'Christmas Break'
            return 'Winter Break'
        
        if is_multi_day:
            if month == 12:
                return 'Christmas Break'
            if month == 2 and is_multi_day:
                return 'Winter Break'
            if month == 10 and is_multi_day:
                return 'Fall Break'
            if month in [3, 4] and is_multi_day:
                return 'Spring Break'
            if month == 11 and is_multi_day:
                return 'Thanksgiving Break'
        
        if month == 10:
            return 'Fall Break'
        
        return label or 'Student Holiday'
    
    date_entries = []
    first_day_of_school = None
    
    for entry in raw_result.get('rawDates', []):
        label_lower = (entry.get('label', '') or '').lower()
        if 'first day' in label_lower and 'school' in label_lower:
            first_day_of_school = parse_date(entry.get('date'))
    
    for entry in raw_result.get('rawDates', []):
        start = parse_date(entry.get('date'))
        end = parse_date(entry.get('endDate')) or start
        if start:
            is_day_off = entry.get('isStudentDayOff', True)
            category = entry.get('category', 'other')
            label = entry.get('label', '') or ''
            label_lower = label.lower()
            notes = entry.get('notes', '') or ''
            notes_lower = notes.lower()
            combined_text = label_lower + ' ' + notes_lower
            
            # DEBUG: Log September and October entries
            if start.month in [9, 10]:
                logging.info(f"DEBUG RAW ENTRY: date={entry.get('date')}, endDate={entry.get('endDate')}, label='{label}', category='{category}', isStudentDayOff={is_day_off}, parsed_start={start}, parsed_end={end}")
            
            # EARLY FILTER: Skip Columbus Day / Indigenous Peoples' Day unless explicitly marked as student day off
            # These are typically NOT student holidays in Georgia schools - only include if shaded/highlighted
            if 'columbus' in label_lower or 'indigenous' in label_lower:
                # Only include if there's explicit closure language
                closure_indicators = ['students do not report', 'schools closed', 'student holiday', 
                                     'school holiday', 'day off', 'no school', 'shaded', 'gray', 'orange']
                has_closure = any(ind in combined_text for ind in closure_indicators)
                if not has_closure:
                    logging.info(f"DEBUG FILTERED OUT Columbus Day entry: {start} - {label}")
                    continue  # Skip this entry - Columbus Day is not a student holiday on this calendar
            
            is_calendar_marker = False
            calendar_marker_patterns = [
                'end of nine weeks', 'end of 1st nine weeks', 'end of 2nd nine weeks',
                'end of 3rd nine weeks', 'end of 4th nine weeks', 'end of first nine weeks',
                'end of second nine weeks', 'end of third nine weeks', 'end of fourth nine weeks',
                'first day of school', 'last day of school', 'last day of semester',
                'end of semester', 'report card', 'progress report'
            ]
            for marker in calendar_marker_patterns:
                if marker in label_lower:
                    is_calendar_marker = True
                    break
            
            if is_calendar_marker:
                has_actual_day_off = False
                day_off_indicators = ['teacher work day', 'teacher workday', 'student holiday', 
                                      'student day off', 'professional development', 'planning day',
                                      'teacher planning', 'staff development', 'students out']
                for indicator in day_off_indicators:
                    if indicator in label_lower or indicator in notes_lower:
                        has_actual_day_off = True
                        break
                if not has_actual_day_off:
                    continue
            
            if category == 'early_release':
                is_day_off = False
            
            if 'early release' in label_lower:
                is_day_off = False
                continue
            
            if 'digital learning' in label_lower or 'independent learning' in label_lower or 'virtual learning' in label_lower:
                has_student_holiday = ('student' in combined_text and 'holiday' in combined_text) or \
                                      'student day off' in combined_text or \
                                      'school holiday' in combined_text
                if not has_student_holiday:
                    is_day_off = False
                    continue
            
            if 'independent learning' in label_lower and 'pl day' in label_lower:
                continue
            if label_lower.strip() == 'independent learning / pl day' or label_lower.strip() == 'independent learning/pl day':
                continue
            
            if first_day_of_school and start < first_day_of_school:
                if 'pre-planning' in label_lower or 'preplanning' in label_lower:
                    continue
                if 'staff development' in label_lower and 'student holiday' not in combined_text:
                    continue
            
            if 'student holiday' in combined_text or 'student day off' in combined_text:
                is_day_off = True
            elif 'students do not report' in combined_text or 'student do not report' in combined_text:
                is_day_off = True
            elif category == 'teacher_day' or category == 'teacher_planning':
                if entry.get('isStudentDayOff') == True:
                    is_day_off = True
                elif 'student holiday' in combined_text:
                    is_day_off = True
                elif 'workday' in label_lower or 'work day' in label_lower:
                    is_day_off = True
            
            if is_day_off:
                date_entries.append({
                    'start': start,
                    'end': end or start,
                    'label': label,
                    'category': category,
                    'isStudentDayOff': is_day_off,
                    'visualIndicator': entry.get('visualIndicator', 'none')
                })
    
    if not date_entries:
        return {
            'success': True,
            'schoolName': raw_result.get('schoolName', ''),
            'schoolYear': raw_result.get('schoolYear', ''),
            'holidays': [],
            'omittedHolidays': [],
            'confidence': raw_result.get('confidence', 'low'),
            'notes': 'No student days off found'
        }
    
    date_entries.sort(key=lambda x: x['start'])
    
    merged = []
    current = None
    
    for entry in date_entries:
        if current is None:
            current = {
                'start': entry['start'],
                'end': entry['end'],
                'labels': [entry['label']],
                'categories': [entry['category']]
            }
        else:
            next_day_after_current = current['end'] + timedelta(days=1)
            gap_days = (entry['start'] - current['end']).days
            
            should_merge = False
            
            if gap_days <= 1:
                should_merge = True
            elif gap_days <= 3:
                if current['end'].weekday() == 4 and entry['start'].weekday() == 0:
                    should_merge = True
                elif current['end'].weekday() == 4 and entry['start'].weekday() == 1:
                    should_merge = True
                elif current['end'].weekday() == 5 and entry['start'].weekday() == 0:
                    should_merge = True
                elif current['end'].weekday() == 6 and entry['start'].weekday() == 0:
                    should_merge = True
                elif entry['start'].weekday() == 0 and gap_days <= 3:
                    should_merge = True
            
            if current['end'].month != entry['start'].month:
                if current['end'].day >= 28 and entry['start'].day <= 5:
                    if gap_days <= 5:
                        should_merge = True
            
            if should_merge:
                current['end'] = max(current['end'], entry['end'])
                current['labels'].append(entry['label'])
                current['categories'].append(entry['category'])
            else:
                merged.append(current)
                current = {
                    'start': entry['start'],
                    'end': entry['end'],
                    'labels': [entry['label']],
                    'categories': [entry['category']]
                }
    
    if current:
        merged.append(current)
    
    holidays = []
    for m in merged:
        primary_label = ''
        for label in m['labels']:
            if label and 'break' in label.lower():
                primary_label = label
                break
        if not primary_label and m['labels']:
            primary_label = m['labels'][0]
        
        start_month = m['start'].month
        duration_days = (m['end'] - m['start']).days
        is_multi_day = duration_days >= 2
        name = get_break_name(start_month, primary_label, is_multi_day)
        
        if name == 'Christmas Break' and m['end'].month == 1:
            pass
        
        holidays.append({
            'name': name,
            'startDate': m['start'].strftime('%Y-%m-%d'),
            'endDate': m['end'].strftime('%Y-%m-%d'),
            'isOmitted': False,
            'notes': f"Merged from: {', '.join(set(m['labels']))}" if len(m['labels']) > 1 else ''
        })
        
        if start_month == 2 and is_multi_day:
            if name == 'Winter Break':
                holidays.append({
                    'name': 'Presidents Day',
                    'startDate': m['start'].strftime('%Y-%m-%d'),
                    'endDate': m['end'].strftime('%Y-%m-%d'),
                    'isOmitted': False,
                    'notes': 'Also interpreted as Presidents Day Weekend (overlapping with Winter Break)'
                })
            elif name == 'Presidents Day':
                holidays.append({
                    'name': 'Winter Break',
                    'startDate': m['start'].strftime('%Y-%m-%d'),
                    'endDate': m['end'].strftime('%Y-%m-%d'),
                    'isOmitted': False,
                    'notes': 'Also interpreted as Winter Break (overlapping with Presidents Day)'
                })
    
    fall_breaks = [h for h in holidays if h['name'] == 'Fall Break']
    if len(fall_breaks) > 1:
        def get_duration(holiday):
            start = datetime.strptime(holiday['startDate'], '%Y-%m-%d')
            end = datetime.strptime(holiday['endDate'], '%Y-%m-%d')
            return (end - start).days
        
        fall_breaks_sorted = sorted(fall_breaks, key=get_duration, reverse=True)
        longest_fall_break = fall_breaks_sorted[0]
        
        for h in holidays:
            if h['name'] == 'Fall Break' and h != longest_fall_break:
                original_label = h.get('notes', '').replace('Merged from: ', '') if h.get('notes') else ''
                if original_label and 'teacher' in original_label.lower():
                    h['name'] = 'Teacher Work Day'
                elif original_label:
                    h['name'] = original_label
                else:
                    h['name'] = 'Student Holiday'
    
    # Consolidate February holidays (Feb 15-28 range) into a single Winter Break
    # This handles cases where Presidents Day is listed separately from February Break
    school_year = raw_result.get('schoolYear', '')
    if school_year:
        try:
            spring_year = int(school_year.split('-')[1])  # 2026-2027 -> 2027
            # Find all February holidays (Presidents Day week range, typically Feb 15-28)
            feb_holidays = []
            other_holidays_feb = []
            for h in holidays:
                start_str = h.get('startDate', '')
                if start_str:
                    start_date = datetime.strptime(start_str, '%Y-%m-%d')
                    # Check if it's in February during Presidents Day/Winter Break range
                    if start_date.month == 2 and start_date.year == spring_year and start_date.day >= 14:
                        feb_holidays.append(h)
                    else:
                        other_holidays_feb.append(h)
                else:
                    other_holidays_feb.append(h)
            
            if len(feb_holidays) >= 1:
                # Merge all February holidays (Feb 14+) into one Winter Break
                all_feb_dates = []
                for h in feb_holidays:
                    start = datetime.strptime(h['startDate'], '%Y-%m-%d')
                    end = datetime.strptime(h.get('endDate', h['startDate']), '%Y-%m-%d')
                    current = start
                    while current <= end:
                        all_feb_dates.append(current)
                        current += timedelta(days=1)
                
                if all_feb_dates:
                    min_feb_date = min(all_feb_dates)
                    max_feb_date = max(all_feb_dates)
                    # Exclude weekends from the end
                    while max_feb_date.weekday() >= 5 and max_feb_date > min_feb_date:
                        max_feb_date -= timedelta(days=1)
                    
                    merged_feb_labels = list(set([h.get('name', '') for h in feb_holidays]))
                    
                    consolidated_winter = {
                        'name': 'Winter Break',
                        'startDate': min_feb_date.strftime('%Y-%m-%d'),
                        'endDate': max_feb_date.strftime('%Y-%m-%d'),
                        'isOmitted': False,
                        'notes': f"Consolidated from: {', '.join(merged_feb_labels)}" if len(merged_feb_labels) > 1 else ''
                    }
                    
                    # Replace holidays list with consolidated version
                    holidays = other_holidays_feb + [consolidated_winter]
        except Exception as e:
            pass  # If consolidation fails, leave as-is
    
    # Consolidate November holidays (Nov 22-27 range) into a single Thanksgiving Break
    # This handles cases where Inclement Weather Days, etc. are listed separately from Thanksgiving Break
    if school_year:
        try:
            fall_year = int(school_year.split('-')[0])
            # Find all November holidays
            nov_holidays = []
            other_holidays = []
            for h in holidays:
                start_str = h.get('startDate', '')
                if start_str:
                    start_date = datetime.strptime(start_str, '%Y-%m-%d')
                    # Check if it's in November during Thanksgiving week range (days 22-30)
                    if start_date.month == 11 and start_date.year == fall_year and start_date.day >= 22:
                        nov_holidays.append(h)
                    else:
                        other_holidays.append(h)
                else:
                    other_holidays.append(h)
            
            if len(nov_holidays) >= 2:
                # Only consolidate if we have multiple November holidays to merge
                # Merge all November holidays (Nov 22+) into one Thanksgiving Break
                all_dates = []
                for h in nov_holidays:
                    start = datetime.strptime(h['startDate'], '%Y-%m-%d')
                    end = datetime.strptime(h.get('endDate', h['startDate']), '%Y-%m-%d')
                    current = start
                    while current <= end:
                        all_dates.append(current)
                        current += timedelta(days=1)
                
                if all_dates:
                    min_date = min(all_dates)
                    max_date = max(all_dates)
                    # Exclude weekends from the end
                    while max_date.weekday() >= 5 and max_date > min_date:
                        max_date -= timedelta(days=1)
                    
                    # Calculate the actual Thanksgiving day (4th Thursday of November)
                    nov_first = datetime(fall_year, 11, 1)
                    days_until_thursday = (3 - nov_first.weekday()) % 7
                    first_thursday = nov_first + timedelta(days=days_until_thursday)
                    actual_thanksgiving = first_thursday + timedelta(weeks=3)
                    
                    # Validate: consolidated break should be at least 3 days and include Thanksgiving
                    duration_days = (max_date - min_date).days + 1
                    includes_thanksgiving = min_date <= actual_thanksgiving <= max_date
                    
                    if duration_days >= 3 and includes_thanksgiving:
                        # Good consolidation - use it
                        merged_labels = list(set([h.get('name', '') for h in nov_holidays]))
                        
                        consolidated_thanksgiving = {
                            'name': 'Thanksgiving Break',
                            'startDate': min_date.strftime('%Y-%m-%d'),
                            'endDate': max_date.strftime('%Y-%m-%d'),
                            'isOmitted': False,
                            'notes': f"Consolidated from: {', '.join(merged_labels)}" if len(merged_labels) > 1 else ''
                        }
                        
                        # Replace holidays list with consolidated version
                        holidays = other_holidays + [consolidated_thanksgiving]
                    # If bad consolidation, leave holidays as-is - the fallback will handle it
        except Exception as e:
            pass  # If consolidation fails, leave as-is
    
    # Fallback: If Thanksgiving Break is missing, infer from school year
    thanksgiving_found = any(h['name'] == 'Thanksgiving Break' for h in holidays)
    if not thanksgiving_found:
        school_year = raw_result.get('schoolYear', '')
        if school_year:
            try:
                # Parse school year (e.g., "2027-2028" -> fall year is 2027)
                fall_year = int(school_year.split('-')[0])
                # Calculate 4th Thursday of November
                # November 1st of that year
                nov_first = datetime(fall_year, 11, 1)
                # Find first Thursday (weekday 3)
                days_until_thursday = (3 - nov_first.weekday()) % 7
                first_thursday = nov_first + timedelta(days=days_until_thursday)
                # 4th Thursday is 3 weeks later
                thanksgiving_day = first_thursday + timedelta(weeks=3)
                # Georgia Thanksgiving Break: typically Mon before through Fri after
                # Standard: Mon-Fri of Thanksgiving week
                monday_of_week = thanksgiving_day - timedelta(days=thanksgiving_day.weekday())
                friday_of_week = monday_of_week + timedelta(days=4)
                
                holidays.append({
                    'name': 'Thanksgiving Break',
                    'startDate': monday_of_week.strftime('%Y-%m-%d'),
                    'endDate': friday_of_week.strftime('%Y-%m-%d'),
                    'isOmitted': False,
                    'notes': 'Inferred from school year (OCR may have missed this)'
                })
            except Exception as e:
                pass  # If inference fails, leave it missing
    
    standard_holidays = [
        'MLK Day', 'Presidents Day', 'Spring Break', 'Easter', 'Memorial Day',
        'Labor Day', 'Fall Break', 'Veterans Day', 'Thanksgiving Break', 
        'Christmas Break', 'Winter Break'
    ]
    found_names = {h['name'] for h in holidays}
    omitted = [h for h in standard_holidays if h not in found_names]
    
    if 'Christmas Break' in omitted:
        omitted.remove('Christmas Break')
    
    return {
        'success': True,
        'schoolName': raw_result.get('schoolName', ''),
        'schoolYear': raw_result.get('schoolYear', ''),
        'holidays': holidays,
        'omittedHolidays': omitted,
        'confidence': raw_result.get('confidence', 'high'),
        'notes': f"Processed {len(raw_result.get('rawDates', []))} raw dates into {len(holidays)} holidays/breaks",
        '_rawDatesExtracted': len(raw_result.get('rawDates', [])),
        '_legendInfo': raw_result.get('legendInfo', '')
    }


def validate_and_filter_calendar_dates(calendar_result):
    """
    Post-processing validation to remove incorrectly extracted dates:
    1. Remove weekends from break end dates (breaks end on last school day)
    2. Remove known unshaded holidays that shouldn't be extracted
    3. Trim breaks to exclude Saturday/Sunday end dates
    """
    from datetime import datetime, timedelta
    
    if not calendar_result.get('holidays'):
        return calendar_result
    
    holidays = calendar_result.get('holidays', [])
    validated = []
    
    for h in holidays:
        name = h.get('name', '')
        start_str = h.get('startDate')
        end_str = h.get('endDate')
        
        if not start_str:
            continue
        
        try:
            start = datetime.strptime(start_str, '%Y-%m-%d')
            end = datetime.strptime(end_str, '%Y-%m-%d') if end_str else start
        except:
            validated.append(h)
            continue
        
        if 'columbus' in name.lower() or 'indigenous' in name.lower():
            notes = h.get('notes', '') or ''
            if 'shaded' not in notes.lower() and 'gray' not in notes.lower() and 'orange' not in notes.lower():
                continue
        
        while end.weekday() >= 5 and end > start:
            end = end - timedelta(days=1)
        
        h['endDate'] = end.strftime('%Y-%m-%d')
        validated.append(h)
    
    calendar_result['holidays'] = validated
    return calendar_result


def normalize_georgia_calendar(calendar_result):
    """
    Apply Georgia-specific normalization rules to calendar data:
    1. December breaks = "Christmas Break" (even if labeled "Winter Break")
    2. February breaks = "Winter Break" (the only Winter Break)
    3. Merge adjacent holidays (Presidents Day + Feb Break = Winter Break)
    4. Christmas Break extends into January if those days are student days off
    5. Remove duplicate entries for same date ranges
    """
    from datetime import datetime, timedelta
    
    if not calendar_result.get('holidays'):
        return calendar_result
    
    holidays = calendar_result.get('holidays', [])
    
    def parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except:
            return None
    
    normalized = []
    christmas_break = None
    winter_break_candidates = []
    presidents_day = None
    
    for h in holidays:
        start = parse_date(h.get('startDate'))
        end = parse_date(h.get('endDate'))
        name = h.get('name', '')
        
        if not start:
            continue
        
        if start.month == 12 or (start.month == 11 and end and end.month == 12):
            h['name'] = 'Christmas Break'
            if christmas_break is None:
                christmas_break = h.copy()
                christmas_break['_start'] = start
                christmas_break['_end'] = end
            else:
                if end and end > christmas_break['_end']:
                    christmas_break['endDate'] = h['endDate']
                    christmas_break['_end'] = end
            continue
        
        if start.month == 1 and start.day <= 10:
            if christmas_break is not None:
                christmas_end = christmas_break['_end']
                gap = (start - christmas_end).days
                if gap <= 5:
                    if end and end > christmas_break['_end']:
                        christmas_break['endDate'] = h['endDate']
                        christmas_break['_end'] = end
                    elif start > christmas_break['_end']:
                        christmas_break['endDate'] = h['endDate'] or h['startDate']
                        christmas_break['_end'] = end or start
                    continue
        
        if start.month == 2:
            if 'president' in name.lower():
                presidents_day = h.copy()
                presidents_day['_start'] = start
                presidents_day['_end'] = end
            elif 'winter' in name.lower() or 'break' in name.lower():
                winter_break_candidates.append({
                    'holiday': h.copy(),
                    '_start': start,
                    '_end': end
                })
            else:
                winter_break_candidates.append({
                    'holiday': h.copy(),
                    '_start': start,
                    '_end': end
                })
            continue
        
        normalized.append(h)
    
    if christmas_break:
        del christmas_break['_start']
        del christmas_break['_end']
        normalized.append(christmas_break)
    
    if presidents_day or winter_break_candidates:
        all_feb_dates = []
        
        if presidents_day:
            all_feb_dates.append((presidents_day['_start'], presidents_day['_end']))
        
        for wbc in winter_break_candidates:
            all_feb_dates.append((wbc['_start'], wbc['_end']))
        
        if all_feb_dates:
            all_feb_dates.sort(key=lambda x: x[0])
            
            merged_start = all_feb_dates[0][0]
            merged_end = all_feb_dates[0][1] or all_feb_dates[0][0]
            
            for start, end in all_feb_dates[1:]:
                end = end or start
                gap = (start - merged_end).days
                if gap <= 3:
                    merged_end = max(merged_end, end)
                else:
                    normalized.append({
                        'name': 'Winter Break',
                        'startDate': merged_start.strftime('%Y-%m-%d'),
                        'endDate': merged_end.strftime('%Y-%m-%d'),
                        'isOmitted': False,
                        'notes': 'Merged February break (includes Presidents Day weekend)'
                    })
                    merged_start = start
                    merged_end = end
            
            normalized.append({
                'name': 'Winter Break',
                'startDate': merged_start.strftime('%Y-%m-%d'),
                'endDate': merged_end.strftime('%Y-%m-%d'),
                'isOmitted': False,
                'notes': 'Merged February break (includes Presidents Day weekend)' if presidents_day else ''
            })
    
    seen_ranges = set()
    deduplicated = []
    for h in normalized:
        key = (h.get('startDate'), h.get('endDate'), h.get('name'))
        if key not in seen_ranges:
            seen_ranges.add(key)
            deduplicated.append(h)
    
    deduplicated.sort(key=lambda x: x.get('startDate', ''))
    
    calendar_result['holidays'] = deduplicated
    calendar_result['_normalized'] = True
    calendar_result['_normalizationRules'] = 'Georgia (December=Christmas Break, February=Winter Break, adjacent holidays merged)'
    
    return calendar_result


def analyze_school_calendar_two_pass(text, shading_info=None):
    """
    Two-pass school calendar analysis:
    Pass 1: Extract all raw dates with visual indicators
    Pass 2: Apply Python merge logic and normalize break names
    """
    logger.info("Starting two-pass school calendar analysis...")
    
    enhanced_text = text
    if shading_info:
        by_month_color = {}
        for item in shading_info:
            month = item.get('month') or 'Unknown'
            color = item.get('color', 'unknown')
            day = item.get('day')
            key = (month, color)
            if key not in by_month_color:
                by_month_color[key] = []
            by_month_color[key].append(day)
        
        shading_summary = "\n\nVISUAL SHADING DETECTED IN PDF CALENDAR CELLS:\n"
        shading_summary += "(Yellow/blue shading typically indicates Student Holiday or Student Day Off)\n"
        for (month, color), days in sorted(by_month_color.items()):
            days_sorted = sorted(set(days))
            if len(days_sorted) >= 2:
                day_ranges = []
                start = days_sorted[0]
                end = days_sorted[0]
                for d in days_sorted[1:]:
                    if d == end + 1:
                        end = d
                    else:
                        day_ranges.append(f"{start}-{end}" if start != end else str(start))
                        start = end = d
                day_ranges.append(f"{start}-{end}" if start != end else str(start))
                days_str = ', '.join(day_ranges)
            else:
                days_str = ', '.join(str(d) for d in days_sorted)
            shading_summary += f"- {month}: {color.upper()} shading on days {days_str} (likely Student Holiday)\n"
        enhanced_text = text + shading_summary
        logger.info(f"Enhanced text with shading info for {len(by_month_color)} month/color groups")
    
    raw_result = extract_raw_calendar_dates(enhanced_text)
    logger.info(f"Pass 1 complete: extracted {len(raw_result.get('rawDates', []))} raw dates")
    
    merged_result = merge_and_normalize_breaks(raw_result)
    logger.info(f"Pass 2 complete: merged into {len(merged_result.get('holidays', []))} holidays/breaks")
    
    if shading_info:
        merged_result = add_missing_breaks_from_shading(merged_result, shading_info)
    
    return merged_result


def add_missing_breaks_from_shading(calendar_result, shading_info):
    """Add any missing multi-day breaks detected from shading but missed by AI extraction."""
    from datetime import datetime
    
    existing_breaks = {h['name']: h for h in calendar_result.get('holidays', [])}
    
    by_month = {}
    for item in shading_info:
        month = item.get('month')
        day = item.get('day')
        if month and day:
            if month not in by_month:
                by_month[month] = []
            by_month[month].append(day)
    
    school_year = calendar_result.get('schoolYear', '')
    year_match = None
    if school_year:
        import re
        match = re.search(r'(\d{4})-(\d{2,4})', school_year)
        if match:
            year_match = (int(match.group(1)), int(match.group(2)) if len(match.group(2)) == 4 else 2000 + int(match.group(2)))
    
    month_to_num = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
                    'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12}
    
    def is_weekend_gap(year, month, day1, day2):
        """Check if all days between day1 and day2 (exclusive) are weekends."""
        if day2 <= day1 + 1:
            return True
        for d in range(day1 + 1, day2):
            try:
                dt = datetime(year, month, d)
                if dt.weekday() < 5:
                    return False
            except ValueError:
                return False
        return True
    
    for month_name, days in by_month.items():
        days = sorted(set(days))
        if len(days) < 2:
            continue
        
        month_num = month_to_num.get(month_name)
        if not month_num or not year_match:
            continue
        
        year = year_match[1] if month_num <= 6 else year_match[0]
        
        consecutive_runs = []
        start = days[0]
        end = days[0]
        for d in days[1:]:
            if d == end + 1 or is_weekend_gap(year, month_num, end, d):
                end = d
            else:
                if end - start >= 1:
                    consecutive_runs.append((start, end))
                start = end = d
        if end - start >= 1:
            consecutive_runs.append((start, end))
        
        for start_day, end_day in consecutive_runs:
            if month_num == 2:
                if 'Winter Break' not in existing_breaks and 'Presidents Day' not in existing_breaks:
                    year = year_match[1]
                    if 10 <= start_day <= 16 and 10 <= end_day <= 20:
                        import calendar as cal
                        _, last_day = cal.monthrange(year, 2)
                        if end_day > last_day:
                            end_day = last_day
                    try:
                        start_date = datetime(year, month_num, start_day)
                        end_date = datetime(year, month_num, end_day)
                        
                        new_break = {
                            'name': 'Winter Break',
                            'startDate': start_date.strftime('%Y-%m-%d'),
                            'endDate': end_date.strftime('%Y-%m-%d'),
                            'isOmitted': False,
                            'notes': 'Detected from visual shading in calendar'
                        }
                        calendar_result['holidays'].append(new_break)
                        existing_breaks['Winter Break'] = new_break
                        logger.info(f"Added Winter Break from shading: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                        
                        presidents_break = {
                            'name': 'Presidents Day',
                            'startDate': start_date.strftime('%Y-%m-%d'),
                            'endDate': end_date.strftime('%Y-%m-%d'),
                            'isOmitted': False,
                            'notes': 'Also interpreted as Presidents Day (overlapping with Winter Break)'
                        }
                        calendar_result['holidays'].append(presidents_break)
                        existing_breaks['Presidents Day'] = presidents_break
                    except ValueError as e:
                        logger.warning(f"Could not create February break dates: {e}")
    
    return calendar_result


def infer_missing_years(calendar_result):
    """
    Infer missing year dates for holidays and breaks within the 24-month calendar range.
    Uses proper federal holiday rules and pattern matching.
    For holidays outside the provided calendar's range, looks BACKWARD to previous years.
    Marks inferred dates with 'inferred': True.
    
    IMPORTANT: Inferred breaks that end before today are skipped (fully past).
    However, if today falls within a break (start is past but end is future), 
    the break is kept so the frontend can populate from today onward.
    
    NOTE: Uses get_effective_date() to support admin date override for testing.
    """
    from datetime import datetime, timedelta, date
    import calendar as cal
    
    if not calendar_result.get('holidays'):
        return calendar_result
    
    effective_date = get_effective_date()
    today = datetime.combine(effective_date, datetime.min.time())
    
    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except:
            return None
    
    def get_nth_weekday_of_month(year, month, weekday, n):
        """Get the nth occurrence of a weekday in a month (1-indexed)."""
        first_day = datetime(year, month, 1)
        first_weekday = first_day.weekday()
        days_to_target = (weekday - first_weekday) % 7
        first_occurrence = 1 + days_to_target
        target_day = first_occurrence + (n - 1) * 7
        last_day = cal.monthrange(year, month)[1]
        if target_day > last_day:
            return None
        return datetime(year, month, target_day)
    
    def get_nth_full_week(dt):
        """Determine which Nth full week (Mon-Fri) this date falls in.
        A full week is one where Mon-Fri are all in the same month.
        E.g., Oct 12, 2026 (Monday) is in the 2nd full week of October 2026.
        """
        first_day = dt.replace(day=1)
        first_weekday = first_day.weekday()
        
        days_to_first_monday = (7 - first_weekday) % 7 if first_weekday != 0 else 0
        first_monday = 1 + days_to_first_monday
        
        if first_monday > 1:
            first_full_week_monday = first_monday
        else:
            first_full_week_monday = 1
        
        last_day = cal.monthrange(dt.year, dt.month)[1]
        if first_full_week_monday + 4 > last_day:
            first_full_week_monday += 7
        
        week_start = dt.day - dt.weekday()
        if week_start < 1:
            week_start = 1
        
        weeks_from_first = (week_start - first_full_week_monday) // 7
        return weeks_from_first + 1 if weeks_from_first >= 0 else 1
    
    def get_last_weekday_of_month(year, month, weekday):
        """Get the last occurrence of a weekday in a month."""
        last_day = cal.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day)
        days_back = (last_date.weekday() - weekday) % 7
        return last_date - timedelta(days=days_back)
    
    def get_nth_full_week_start(year, month, nth_full_week):
        """Get the Monday of the Nth full week in the given month.
        A full week is one where Mon-Fri are all in the same month.
        """
        first_day = datetime(year, month, 1)
        first_weekday = first_day.weekday()
        
        if first_weekday == 0:
            first_full_week_monday = 1
        else:
            first_full_week_monday = 1 + (7 - first_weekday)
        
        last_day = cal.monthrange(year, month)[1]
        if first_full_week_monday + 4 > last_day:
            first_full_week_monday += 7
        
        target_monday = first_full_week_monday + (nth_full_week - 1) * 7
        
        if target_monday > last_day:
            target_monday = first_full_week_monday + max(0, nth_full_week - 2) * 7
        
        if target_monday < 1 or target_monday > last_day:
            return datetime(year, month, first_full_week_monday)
        
        return datetime(year, month, target_monday)
    
    def normalize_name(name):
        return name.lower().strip().replace("'", "").replace("'", "")
    
    def get_federal_holiday_date(holiday_name, year):
        """Calculate federal holiday dates based on official rules."""
        name = normalize_name(holiday_name)
        
        if 'labor' in name and 'day' in name:
            return get_nth_weekday_of_month(year, 9, 0, 1), None  # First Monday of September
        
        if 'thanksgiving' in name:
            thanksgiving_thu = get_nth_weekday_of_month(year, 11, 3, 4)  # Fourth Thursday of November
            if thanksgiving_thu:
                return thanksgiving_thu, None  # Return None for end - let caller use source duration
        
        if 'mlk' in name or 'martin luther king' in name:
            return get_nth_weekday_of_month(year, 1, 0, 3), None  # Third Monday of January
        
        if 'presidents' in name or 'president' in name:
            return get_nth_weekday_of_month(year, 2, 0, 3), None  # Third Monday of February
        
        if 'memorial' in name and 'day' in name:
            return get_last_weekday_of_month(year, 5, 0), None  # Last Monday of May
        
        if 'independence' in name or 'july 4' in name or '4th of july' in name:
            return datetime(year, 7, 4), None
        
        return None, None
    
    holidays_by_name_year = {}
    all_dates = []
    
    for holiday in calendar_result['holidays']:
        start_date = parse_date(holiday.get('startDate', ''))
        end_date = parse_date(holiday.get('endDate', ''))
        if start_date:
            all_dates.append(start_date)
            key = (normalize_name(holiday.get('name', '')), start_date.year)
            holidays_by_name_year[key] = holiday
        if end_date:
            all_dates.append(end_date)
    
    if not all_dates:
        return calendar_result
    
    min_extracted = min(all_dates)
    max_extracted = max(all_dates)
    
    calendar_school_year = max_extracted.year if max_extracted.month <= 6 else max_extracted.year + 1
    
    calendar_range_start = today
    calendar_range_end = today + timedelta(days=731)
    
    enhanced_holidays = []
    
    for holiday in calendar_result['holidays']:
        holiday['inferred'] = False
        enhanced_holidays.append(holiday)
    
    def infer_christmas_break(target_year, source_holiday):
        """Infer Christmas Break based on source pattern.
        Preserves source duration while ensuring break includes at least Jan 1.
        """
        source_start = parse_date(source_holiday.get('startDate', ''))
        source_end = parse_date(source_holiday.get('endDate', ''))
        if not source_start or not source_end:
            return None, None
        
        source_start_day = source_start.day
        duration = (source_end - source_start).days
        source_end_month = source_end.month
        
        try:
            start = datetime(target_year, 12, source_start_day)
            if start.weekday() != source_start.weekday():
                diff = source_start.weekday() - start.weekday()
                start = start + timedelta(days=diff)
                if start.day > 25:
                    start = start - timedelta(days=7)
            end = start + timedelta(days=duration)
            
            if source_end_month == 1:
                new_years_day = datetime(target_year + 1, 1, 1)
                if end < new_years_day:
                    end = new_years_day
            
            return start, end
        except:
            return None, None
    
    def infer_break_by_pattern(target_year, source_holiday):
        """Infer a break date by matching the Nth full week pattern from source.
        Preserves:
        1. The Nth full week (e.g., 2nd full week of October)
        2. The weekday offset (e.g., starts on Thursday, not Monday)
        3. The exact duration (e.g., 5 days)
        
        E.g., if source is Thursday of the 2nd full week of October lasting 5 days,
        inferred will also be Thursday of the 2nd full week lasting 5 days.
        """
        source_start = parse_date(source_holiday.get('startDate', ''))
        source_end = parse_date(source_holiday.get('endDate', ''))
        if not source_start or not source_end:
            return None, None
        
        duration = (source_end - source_start).days
        start_month = source_start.month
        source_weekday = source_start.weekday()
        nth_full_week = get_nth_full_week(source_start)
        
        week_monday = get_nth_full_week_start(target_year, start_month, nth_full_week)
        
        inferred_start = week_monday + timedelta(days=source_weekday)
        inferred_end = inferred_start + timedelta(days=duration)
        
        return inferred_start, inferred_end
    
    unique_holidays = {}
    for holiday in calendar_result['holidays']:
        name = normalize_name(holiday.get('name', ''))
        if name not in unique_holidays:
            unique_holidays[name] = holiday
    
    for holiday_name, source_holiday in unique_holidays.items():
        source_start = parse_date(source_holiday.get('startDate', ''))
        source_end = parse_date(source_holiday.get('endDate', ''))
        
        if not source_start or not source_end:
            continue
        if source_holiday.get('isOmitted'):
            continue
        
        source_year = source_start.year
        duration = (source_end - source_start).days
        
        target_years = []
        for year in range(calendar_range_start.year, calendar_range_end.year + 1):
            if year != source_year:
                existing_key = (holiday_name, year)
                if existing_key not in holidays_by_name_year:
                    target_years.append(year)
        
        for target_year in target_years:
            try:
                inferred_start, inferred_end = None, None
                
                federal_start, federal_end = get_federal_holiday_date(holiday_name, target_year)
                if federal_start:
                    if 'thanksgiving' in holiday_name:
                        source_start_weekday = source_start.weekday()
                        thanksgiving_thu = federal_start
                        if source_start_weekday == 0:  # Source starts Monday
                            inferred_start = thanksgiving_thu - timedelta(days=3)  # Mon before Thu
                        else:
                            inferred_start = thanksgiving_thu - timedelta(days=(3 - source_start_weekday) % 7)
                        inferred_end = inferred_start + timedelta(days=duration)
                    else:
                        inferred_start = federal_start
                        if federal_end:
                            inferred_end = federal_end
                        else:
                            inferred_end = federal_start + timedelta(days=duration)
                elif 'christmas' in holiday_name or ('winter' in holiday_name and source_start.month == 12):
                    inferred_start, inferred_end = infer_christmas_break(target_year, source_holiday)
                elif 'winter' in holiday_name and source_start.month == 2:
                    inferred_start, inferred_end = infer_break_by_pattern(target_year, source_holiday)
                elif 'spring' in holiday_name:
                    inferred_start, inferred_end = infer_break_by_pattern(target_year, source_holiday)
                elif 'fall' in holiday_name:
                    inferred_start, inferred_end = infer_break_by_pattern(target_year, source_holiday)
                else:
                    inferred_start, inferred_end = infer_break_by_pattern(target_year, source_holiday)
                
                if not inferred_start or not inferred_end:
                    continue
                
                if inferred_end < today:
                    continue
                
                if inferred_start > calendar_range_end:
                    continue
                
                if inferred_end > calendar_range_end:
                    inferred_end = calendar_range_end
                
                inferred_holiday = {
                    'name': source_holiday['name'],
                    'startDate': inferred_start.strftime('%Y-%m-%d'),
                    'endDate': inferred_end.strftime('%Y-%m-%d'),
                    'isOmitted': False,
                    'inferred': True,
                    'sourceYear': source_year,
                    'notes': f"Inferred from {source_year} calendar"
                }
                enhanced_holidays.append(inferred_holiday)
                holidays_by_name_year[(holiday_name, target_year)] = inferred_holiday
            except Exception as e:
                logger.warning(f"Could not infer date for {source_holiday['name']} in {target_year}: {e}")
    
    enhanced_holidays.sort(key=lambda h: h.get('startDate', ''))
    
    calendar_result['holidays'] = enhanced_holidays
    return calendar_result


def get_or_create_school_entity(district_name, entity_type='public_district', county=None):
    """
    Find or create a school entity (district or private school) in the database.
    Returns the SchoolEntity object.
    """
    if not district_name:
        return None
    
    normalized_name = SchoolEntity.normalize_name(district_name)
    normalized_county = county.strip() if county else None
    
    entity = SchoolEntity.query.filter_by(
        entity_type=entity_type,
        normalized_name=normalized_name,
        county=normalized_county
    ).first()
    
    if not entity:
        entity = SchoolEntity(
            entity_type=entity_type,
            district_name=district_name.strip(),
            normalized_name=normalized_name,
            county=normalized_county
        )
        db.session.add(entity)
        db.session.commit()
        logger.info(f"Created new school entity: {district_name} ({entity_type}) in {county or 'N/A'}")
    
    return entity



@main.route('/extract_school_calendar', methods=['POST'])
def extract_school_calendar():
    """Extract holiday dates from an uploaded school calendar PDF or image."""
    step = "init"
    try:
        step = "auth_check"
        if not current_user.is_authenticated:
            ip_address = get_client_ip()
            guest = get_or_create_guest_token(ip_address)
            if guest.tokens <= 0:
                return jsonify({'error': 'No tokens remaining. Please provide your email or register for more access.'}), 403
        
        step = "file_check"
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        if file.filename == '' or file.filename is None:
            return jsonify({'error': 'No file selected'}), 400
        
        filename_lower = file.filename.lower()
        allowed_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp']
        is_image = any(filename_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
        is_pdf = filename_lower.endswith('.pdf')
        
        if not any(filename_lower.endswith(ext) for ext in allowed_extensions):
            return jsonify({'error': 'Only PDF and image files (PNG, JPG, JPEG, GIF, WEBP) are accepted'}), 400
        
        step = "read_file"
        file_bytes = file.read()
        
        if len(file_bytes) > 20 * 1024 * 1024:
            return jsonify({'error': 'File size exceeds 20MB limit'}), 400
        
        if is_image:
            step = "image_ocr_extraction"
            logger.info(f"Processing image file: {file.filename} - extracting text via OCR")

            # First, do OCR to extract text for school identification
            try:
                ocr_text = extract_text_from_calendar_image_ocr(file_bytes)
            except Exception as ocr_err:
                logger.warning(f"OCR extraction failed: {ocr_err}")
                ocr_text = ""

            # Check if this is a verified school calendar
            step = "verified_school_check"
            verified_school = find_verified_school(ocr_text) if ocr_text else None

            if verified_school:
                school_year = detect_school_year(ocr_text)
                verified_dates = get_verified_calendar_24_months(verified_school)

                if verified_dates:
                    logger.info(f"Found verified calendar for {verified_school} ({school_year}) - skipping AI analysis")
                    calendar_result = {
                        'schoolName': get_display_name(verified_school),
                        'schoolYear': school_year,
                        'holidays': verified_dates,
                        '_meta': {
                            'wasImage': True,
                            'wasScanned': False,
                            'fileType': 'image',
                            'extractionMethod': 'verified_lookup',
                            'verifiedSchool': verified_school,
                            'extractedAt': __import__('datetime').datetime.now().isoformat()
                        }
                    }
                    # Infer missing dates for incomplete years
                    calendar_result = infer_missing_years(calendar_result)
                    return jsonify(calendar_result)

            # No verified match - continue with AI analysis
            step = "image_ocr_analysis"
            logger.info(f"No verified calendar found - using OCR+AI analysis")

            raw_result = analyze_calendar_with_ocr(file_bytes, file.filename)
            extraction_method = 'ocr_plus_ai'
            
            if raw_result is None or not raw_result.get('rawDates'):
                step = "image_vision_fallback"
                logger.info("OCR extraction failed or returned no dates, falling back to Vision API")
                vision_result = analyze_calendar_image_with_vision(file_bytes, file.filename)
                if vision_result and vision_result.get('rawDates'):
                    raw_result = vision_result
                    extraction_method = 'vision_api'
            
            step = "merge_normalize"
            calendar_result = merge_and_normalize_breaks(raw_result)
            
            step = "validate_filter"
            calendar_result = validate_and_filter_calendar_dates(calendar_result)
            
            step = "georgia_normalize"
            calendar_result = normalize_georgia_calendar(calendar_result)
            
            step = "infer_dates"
            calendar_result = infer_missing_years(calendar_result)
            
            step = "build_response"
            calendar_result['_meta'] = {
                'wasImage': True,
                'wasScanned': False,
                'fileType': 'image',
                'extractionMethod': extraction_method,
                'extractedAt': __import__('datetime').datetime.now().isoformat()
            }
        else:
            step = "pdfplumber_check"
            if not pdfplumber:
                return jsonify({'error': 'PDF processing is temporarily unavailable. Please try again later.'}), 503
            
            step = "extract_text"
            extracted_text, is_scanned = extract_text_from_pdf(file_bytes)

            if len(extracted_text) < 50:
                return jsonify({'error': 'Could not extract sufficient text from the document. Please ensure the PDF contains readable text.'}), 400

            # Check if this is a verified school calendar
            step = "verified_school_check"
            verified_school = find_verified_school(extracted_text)

            if verified_school:
                school_year = detect_school_year(extracted_text)
                verified_dates = get_verified_calendar_24_months(verified_school)

                if verified_dates:
                    logger.info(f"Found verified calendar for {verified_school} ({school_year}) - skipping AI analysis")
                    calendar_result = {
                        'schoolName': get_display_name(verified_school),
                        'schoolYear': school_year,
                        'holidays': verified_dates,
                        '_meta': {
                            'wasImage': False,
                            'wasScanned': is_scanned,
                            'fileType': 'pdf',
                            'textLength': len(extracted_text),
                            'extractionMethod': 'verified_lookup',
                            'verifiedSchool': verified_school,
                            'extractedAt': __import__('datetime').datetime.now().isoformat()
                        }
                    }
                    # Infer missing dates for incomplete years
                    calendar_result = infer_missing_years(calendar_result)
                    return jsonify(calendar_result)

            # No verified match - continue with AI analysis
            logger.info(f"No verified calendar found - using AI analysis")

            step = "extract_shading"
            shading_info = extract_calendar_shading(file_bytes)
            logger.info(f"Extracted {len(shading_info)} shaded cells from PDF")

            step = "two_pass_analysis"
            calendar_result = analyze_school_calendar_two_pass(extracted_text, shading_info)
            
            step = "validate_filter"
            calendar_result = validate_and_filter_calendar_dates(calendar_result)
            
            step = "georgia_normalize"
            calendar_result = normalize_georgia_calendar(calendar_result)
            
            step = "infer_dates"
            calendar_result = infer_missing_years(calendar_result)
            
            step = "build_response"
            calendar_result['_meta'] = {
                'wasImage': False,
                'wasScanned': is_scanned,
                'fileType': 'pdf',
                'textLength': len(extracted_text),
                'extractedAt': __import__('datetime').datetime.now().isoformat()
            }
        
        return jsonify(calendar_result)
    
    except Exception as e:
        logger.error(f"Error in extract_school_calendar at step '{step}': {str(e)}")
        return jsonify({'error': str(e), 'failed_at_step': step}), 500


@main.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page."""
    return render_template('privacy_policy.html')


@main.route('/terms-of-service')
def terms_of_service():
    """Terms of Service page."""
    return render_template('terms_of_service.html')


@main.route('/contact')
def contact():
    """Contact page."""
    return render_template('contact.html')


# ===== PUBLIC SCHOOL CALENDAR PAGES =====
# SEO-optimized pages for downloading official Georgia school calendars

@main.route('/georgia-school-calendars')
def school_calendars_index():
    """Public index page listing all Georgia school districts with calendar downloads."""
    entities = SchoolEntity.query.filter_by(is_active=True).order_by(SchoolEntity.county, SchoolEntity.district_name).all()

    # Group by county for display
    counties = {}
    for entity in entities:
        county = entity.county or 'Other'
        if county not in counties:
            counties[county] = []

        # Get count of calendar files and school years available
        file_count = CalendarFile.query.filter_by(school_entity_id=entity.id).count()
        years = db.session.query(VerifiedHoliday.school_year).filter_by(
            school_entity_id=entity.id
        ).distinct().all()

        counties[county].append({
            'entity': entity,
            'file_count': file_count,
            'years_available': sorted([y[0] for y in years], reverse=True)
        })

    # Sort counties alphabetically
    sorted_counties = dict(sorted(counties.items()))

    return render_template('school_calendars_index.html',
        counties=sorted_counties,
        total_schools=len(entities)
    )


@main.route('/georgia-school-calendars/<slug>')
def school_calendar_detail(slug):
    """Individual school district page with verified dates and PDF downloads."""
    entity = SchoolEntity.query.filter_by(slug=slug, is_active=True).first_or_404()

    # Get verified holidays grouped by school year
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

    # Get available school years (sorted newest first)
    available_years = sorted(holidays_by_year.keys(), reverse=True)

    return render_template('school_calendar_detail.html',
        entity=entity,
        holidays_by_year=holidays_by_year,
        calendar_files=calendar_files,
        available_years=available_years
    )


@main.route('/download-calendar/<int:file_id>')
def download_calendar(file_id):
    """Download a calendar PDF file."""
    from flask import send_from_directory, abort
    import os

    calendar_file = CalendarFile.query.get_or_404(file_id)

    # Construct the full path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, calendar_file.file_path)

    if not os.path.exists(file_path):
        abort(404)

    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)

    return send_from_directory(directory, filename, as_attachment=True)


@main.route('/api/school-holidays/<int:entity_id>')
def api_school_holidays(entity_id):
    """API endpoint to get verified holidays for a school entity."""
    entity = SchoolEntity.query.get_or_404(entity_id)

    # Get verified holidays for this school
    holidays = VerifiedHoliday.query.filter_by(school_entity_id=entity.id).order_by(
        VerifiedHoliday.school_year.desc(),
        VerifiedHoliday.start_date
    ).all()

    # Group by school year
    holidays_by_year = {}
    for holiday in holidays:
        if holiday.school_year not in holidays_by_year:
            holidays_by_year[holiday.school_year] = []
        holidays_by_year[holiday.school_year].append({
            'name': holiday.name,
            'start_date': holiday.start_date.isoformat(),
            'end_date': holiday.end_date.isoformat()
        })

    return jsonify({
        'success': True,
        'entity_id': entity.id,
        'district_name': entity.district_name,
        'county': entity.county,
        'holidays_by_year': holidays_by_year
    })


@main.route('/api/school-entities')
def api_school_entities():
    """API endpoint to list all school entities with verified holidays."""
    entities = SchoolEntity.query.filter_by(is_active=True).order_by(
        SchoolEntity.county,
        SchoolEntity.district_name
    ).all()

    result = []
    for entity in entities:
        # Check if this entity has any verified holidays
        holiday_count = VerifiedHoliday.query.filter_by(school_entity_id=entity.id).count()
        if holiday_count > 0:
            result.append({
                'id': entity.id,
                'district_name': entity.district_name,
                'county': entity.county,
                'holiday_count': holiday_count
            })

    return jsonify({
        'success': True,
        'entities': result
    })


@main.route('/sitemap.xml', endpoint='sitemap_xml')
def sitemap_xml():
    """Generate XML sitemap for SEO."""
    from flask import make_response
    import datetime

    base_url = request.url_root.rstrip('/')

    pages = [
        {'loc': '/', 'priority': '1.0', 'changefreq': 'weekly'},
        {'loc': '/ai-calendar', 'priority': '0.9', 'changefreq': 'weekly'},
        {'loc': '/georgia-school-calendars', 'priority': '0.9', 'changefreq': 'weekly'},
        {'loc': '/user-guide', 'priority': '0.8', 'changefreq': 'monthly'},
        {'loc': '/technical-docs', 'priority': '0.6', 'changefreq': 'monthly'},
        {'loc': '/privacy-policy', 'priority': '0.3', 'changefreq': 'yearly'},
        {'loc': '/terms-of-service', 'priority': '0.3', 'changefreq': 'yearly'},
        {'loc': '/contact', 'priority': '0.5', 'changefreq': 'yearly'},
        {'loc': '/login', 'priority': '0.4', 'changefreq': 'monthly'},
        {'loc': '/register', 'priority': '0.4', 'changefreq': 'monthly'},
    ]

    # Add individual school calendar pages dynamically
    school_entities = SchoolEntity.query.filter_by(is_active=True).all()
    for entity in school_entities:
        if entity.slug:
            pages.append({
                'loc': f'/georgia-school-calendars/{entity.slug}',
                'priority': '0.8',
                'changefreq': 'monthly'
            })

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for page in pages:
        xml += '  <url>\n'
        xml += f'    <loc>{base_url}{page["loc"]}</loc>\n'
        xml += f'    <lastmod>{datetime.date.today().isoformat()}</lastmod>\n'
        xml += f'    <changefreq>{page["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{page["priority"]}</priority>\n'
        xml += '  </url>\n'

    xml += '</urlset>'

    response = make_response(xml)
    response.headers['Content-Type'] = 'application/xml'
    return response


@main.route('/sitemap', endpoint='sitemap')
def sitemap_html():
    """Human-readable sitemap page."""
    return render_template('sitemap.html')


@main.route('/robots.txt')
def robots_txt():
    """Serve robots.txt for search engine crawlers."""
    from flask import make_response
    
    base_url = request.url_root.rstrip('/')
    
    content = f"""User-agent: *
Allow: /
Allow: /ai-calendar
Allow: /georgia-school-calendars
Allow: /user-guide
Allow: /technical-docs
Allow: /privacy-policy
Allow: /terms-of-service
Allow: /contact

Disallow: /admin
Disallow: /profile
Disallow: /subscription
Disallow: /saves
Disallow: /api/

Sitemap: {base_url}/sitemap.xml
"""
    
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain'
    return response
