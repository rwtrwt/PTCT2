from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from datetime import datetime


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    is_blocked = db.Column(db.Boolean, default=False)
    subscription_type = db.Column(db.String(20), default='free')
    custom_h4 = db.Column(db.String(255))
    token = db.Column(db.Integer, nullable=False, default=50)
    confirmed = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CalendarSave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    config_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('calendar_saves', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'config_data': self.config_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class GuestToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)
    tokens = db.Column(db.Integer, default=10)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    contact_permission = db.Column(db.Boolean, default=False)
    linked_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    linked_user = db.relationship('User', backref=db.backref('guest_tokens', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'tokens': self.tokens,
            'email': self.email,
            'phone': self.phone,
            'contact_permission': self.contact_permission,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class SchoolEntity(db.Model):
    __tablename__ = 'school_entity'
    
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False, default='public_district')
    district_name = db.Column(db.String(255), nullable=False)
    normalized_name = db.Column(db.String(255), nullable=False, index=True)
    county = db.Column(db.String(100), nullable=True, index=True)
    nces_id = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    website = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    calendars = db.relationship('SchoolCalendar', back_populates='school_entity', lazy=True)
    
    __table_args__ = (
        db.UniqueConstraint('entity_type', 'normalized_name', 'county', name='uix_entity_type_name_county'),
        db.Index('ix_entity_county_name', 'county', 'normalized_name'),
    )
    
    @staticmethod
    def normalize_name(name):
        import re
        normalized = name.lower().strip()
        normalized = re.sub(r'[^\w\s-]', '', normalized)
        normalized = re.sub(r'\s+', '_', normalized)
        return normalized
    
    def to_dict(self):
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'district_name': self.district_name,
            'normalized_name': self.normalized_name,
            'county': self.county,
            'nces_id': self.nces_id,
            'is_active': self.is_active,
            'website': self.website,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'calendar_count': len(list(self.calendars)) if self.calendars else 0
        }


class SchoolCalendar(db.Model):
    __tablename__ = 'school_calendar'
    
    id = db.Column(db.Integer, primary_key=True)
    school_entity_id = db.Column(db.Integer, db.ForeignKey('school_entity.id'), nullable=False)
    school_year = db.Column(db.String(20), nullable=False)
    source_filename = db.Column(db.String(500), nullable=True)
    file_hash = db.Column(db.String(64), nullable=True, unique=True)
    analysis_json = db.Column(db.Text, nullable=True)
    analysis_version = db.Column(db.String(20), nullable=True)
    analysis_generated_at = db.Column(db.DateTime, nullable=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    status = db.Column(db.String(20), default='uploaded')
    ingest_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    school_entity = db.relationship('SchoolEntity', back_populates='calendars')
    uploaded_by = db.relationship('User', backref=db.backref('uploaded_calendars', lazy=True))
    
    __table_args__ = (
        db.UniqueConstraint('school_entity_id', 'school_year', name='uix_entity_school_year'),
        db.Index('ix_calendar_school_year', 'school_year'),
    )
    
    def to_dict(self):
        import json
        return {
            'id': self.id,
            'school_entity_id': self.school_entity_id,
            'school_entity_name': self.school_entity.district_name if self.school_entity else None,
            'school_year': self.school_year,
            'source_filename': self.source_filename,
            'status': self.status,
            'analysis_version': self.analysis_version,
            'analysis_generated_at': self.analysis_generated_at.isoformat() if self.analysis_generated_at else None,
            'analysis_json': json.loads(self.analysis_json) if self.analysis_json else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

