import os


class Config:
    SECRET_KEY = os.environ.get('SESSION_SECRET', os.urandom(32).hex())
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL',
                                             'sqlite:///mydatabase.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # PostgreSQL-specific options (keepalives) only apply when using PostgreSQL
    _db_uri = os.environ.get('DATABASE_URL', '')
    if _db_uri.startswith('postgres'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'connect_args': {
                'keepalives': 1,
                'keepalives_idle': 60,
                'keepalives_interval': 10,
                'keepalives_count': 10,
            }
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
        }
    STRIPE_PUBLIC_KEY = 'pk_live_51Q087G08Qtnm286sDsQqxjqso3o6UvzZuiCCQ1Fz47zHrnjEdkNe76dx403WAFZU48mRQXKeQGCYo8iRM79NWzcP00WGBoBX4J'
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')

    # Add SECURITY_PASSWORD_SALT here
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT',
                                            'default_salt')

    # Mail settings
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS',
                                  'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = "parentingtimepro@gmail.com"
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER',
                                         "parentingtimepro@gmail.com")
