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
    token = db.Column(db.Integer, nullable=False, default=10)
    confirmed = db.Column(db.Boolean, default=False)
    is_government = db.Column(db.Boolean, default=False)
    government_verified = db.Column(db.Boolean, default=False)
    government_oath_accepted = db.Column(db.Boolean, default=False)
    referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    referral_count = db.Column(db.Integer, default=0)
    referral_tokens_earned = db.Column(db.Integer, default=0)

    referred_by = db.relationship('User', remote_side=[id], backref='referrals')

    def generate_referral_code(self):
        import secrets
        import string
        chars = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(chars) for _ in range(8))
        self.referral_code = code
        return code

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
    # New fields for public calendar pages
    official_website = db.Column(db.String(500), nullable=True)  # Main school district website
    calendar_page_url = db.Column(db.String(500), nullable=True)  # Direct link to calendar page
    slug = db.Column(db.String(100), nullable=True, unique=True, index=True)  # URL-friendly name
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    @staticmethod
    def generate_slug(name):
        """Generate URL-friendly slug from district name."""
        import re
        slug = name.lower().strip()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        # Remove common suffixes for cleaner URLs
        slug = re.sub(r'-?(public-schools|school-district|school-system|county-schools|schools)$', '', slug)
        return slug.strip('-')

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
            'official_website': self.official_website,
            'calendar_page_url': self.calendar_page_url,
            'slug': self.slug,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class VerifiedHoliday(db.Model):
    """Verified holiday dates for school calendars."""
    __tablename__ = 'verified_holiday'

    id = db.Column(db.Integer, primary_key=True)
    school_entity_id = db.Column(db.Integer, db.ForeignKey('school_entity.id'), nullable=False)
    school_year = db.Column(db.String(20), nullable=False)  # "2025-2026"
    name = db.Column(db.String(100), nullable=False)  # "Labor Day", "Spring Break"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    # Verification status fields
    is_verified = db.Column(db.Boolean, default=True)  # True for human-verified, False for AI-detected
    source = db.Column(db.String(20), default='manual')  # 'manual', 'ai_detected', 'imported'
    confidence = db.Column(db.Float, nullable=True)  # AI confidence score (0.0-1.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school_entity = db.relationship('SchoolEntity', backref=db.backref('holidays', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_holiday_entity_year', 'school_entity_id', 'school_year'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'school_entity_id': self.school_entity_id,
            'school_year': self.school_year,
            'name': self.name,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'verified': self.is_verified,
            'source': self.source,
            'confidence': self.confidence
        }


class CalendarFile(db.Model):
    """PDF/image files for school calendars."""
    __tablename__ = 'calendar_file'

    id = db.Column(db.Integer, primary_key=True)
    school_entity_id = db.Column(db.Integer, db.ForeignKey('school_entity.id'), nullable=False)
    school_year = db.Column(db.String(20), nullable=False)  # "2025-2026"
    filename = db.Column(db.String(255), nullable=False)  # Original filename
    file_path = db.Column(db.String(500), nullable=False)  # Relative path in Official_Calendars
    file_type = db.Column(db.String(10), default='pdf')  # pdf, png, jpeg
    file_size = db.Column(db.Integer, nullable=True)  # Size in bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    school_entity = db.relationship('SchoolEntity', backref=db.backref('calendar_files', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_file_entity_year', 'school_entity_id', 'school_year'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'school_entity_id': self.school_entity_id,
            'school_year': self.school_year,
            'filename': self.filename,
            'file_path': self.file_path,
            'file_type': self.file_type,
            'file_size': self.file_size
        }


class GovernmentDomain(db.Model):
    """Approved government email domains for automatic verification."""
    __tablename__ = 'government_domain'

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False, index=True)
    approved = db.Column(db.Boolean, default=True)
    approved_by = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'domain': self.domain,
            'approved': self.approved,
            'approved_by': self.approved_by,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class GovernmentRegistrationRequest(db.Model):
    """Pending government registration requests awaiting approval."""
    __tablename__ = 'government_registration_request'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email_domain = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='pending')
    verification_token = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.String(120), nullable=True)

    user = db.relationship('User', backref=db.backref('government_requests', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'email_domain': self.email_domain,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }


class SubscriptionMetrics(db.Model):
    """Track subscription metrics like promotional subscriber count."""
    __tablename__ = 'subscription_metrics'

    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100), unique=True, nullable=False)
    metric_value = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_promo_subscriber_count():
        """Get current count of promotional subscribers."""
        metric = SubscriptionMetrics.query.filter_by(metric_name='promo_subscribers').first()
        return metric.metric_value if metric else 0

    @staticmethod
    def increment_promo_subscribers():
        """Increment promotional subscriber count."""
        metric = SubscriptionMetrics.query.filter_by(metric_name='promo_subscribers').first()
        if not metric:
            metric = SubscriptionMetrics(metric_name='promo_subscribers', metric_value=1)
            db.session.add(metric)
        else:
            metric.metric_value += 1
        db.session.commit()
        return metric.metric_value


class FeedbackPost(db.Model):
    """User feedback posts for the forum."""
    __tablename__ = 'feedback_post'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('feedback_posts', lazy=True))
    votes = db.relationship('FeedbackVote', backref='post', lazy=True, cascade='all, delete-orphan')

    @property
    def upvotes(self):
        return sum(1 for v in self.votes if v.vote_value == 1)

    @property
    def downvotes(self):
        return sum(1 for v in self.votes if v.vote_value == -1)

    @property
    def score(self):
        return self.upvotes - self.downvotes

    def to_dict(self, current_user_id=None):
        user_vote = None
        if current_user_id:
            for v in self.votes:
                if v.user_id == current_user_id:
                    user_vote = v.vote_value
                    break
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else 'Unknown',
            'title': self.title,
            'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'upvotes': self.upvotes,
            'downvotes': self.downvotes,
            'score': self.score,
            'user_vote': user_vote
        }


class FeedbackVote(db.Model):
    """User votes on feedback posts."""
    __tablename__ = 'feedback_vote'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('feedback_post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vote_value = db.Column(db.Integer, nullable=False)  # 1 for upvote, -1 for downvote
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='unique_user_post_vote'),)

    user = db.relationship('User', backref=db.backref('feedback_votes', lazy=True))

