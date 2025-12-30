from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from config import Config
from extensions import db
from models import User
import logging
import sqlalchemy
from flask import Flask
from flask_migrate import Migrate
from extensions import db

mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # Log database connection info (without exposing sensitive data)
    logger.info(f"Attempting to connect to database...")
    logger.info(f"Database type: {app.config['SQLALCHEMY_DATABASE_URI'].split('://')[0]}")

    db.init_app(app)
    mail.init_app(app)

    # Initialize Flask-Migrate
    migrate = Migrate(app, db)

    # Test database connection (non-fatal - don't crash app if DB unavailable at startup)
    with app.app_context():
        try:
            connection = db.engine.connect()
            logger.info("Successfully connected to the database.")
            connection.close()
        except Exception as e:
            logger.warning(f"Database connection test skipped: {str(e)}")

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints here
    from auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # Register payments blueprint
    from payments import create_payments_blueprint
    payments_blueprint = create_payments_blueprint(db)
    app.register_blueprint(payments_blueprint)

    # Register admin blueprint
    from admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint)

    # Global error handlers to return JSON instead of HTML
    from flask import jsonify, request
    import traceback
    
    @app.errorhandler(400)
    def bad_request_error(error):
        return jsonify({'error': 'Bad request', 'details': str(error)}), 400
    
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({'error': 'Not found', 'details': str(error)}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        try:
            db.session.rollback()
        except:
            pass
        error_details = {
            'error': 'Internal server error',
            'message': str(error),
            'path': request.path if request else 'unknown'
        }
        logger.error(f"500 error on {request.path}: {str(error)}")
        return jsonify(error_details), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import HTTPException
        
        tb = traceback.format_exc()
        logger.error(f"Unhandled exception on {request.path}: {str(e)}\n{tb}")
        try:
            db.session.rollback()
        except:
            pass
        
        if isinstance(e, HTTPException):
            error_details = {
                'error': e.description,
                'type': type(e).__name__,
                'path': request.path if request else 'unknown'
            }
            return jsonify(error_details), e.code
        
        error_details = {
            'error': str(e),
            'type': type(e).__name__,
            'path': request.path if request else 'unknown'
        }
        return jsonify(error_details), 500

    @app.context_processor
    def inject_effective_date():
        import json
        from datetime import date
        from flask import session
        from flask_login import current_user
        
        effective_date_json = None
        
        if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
            override_date_str = session.get('admin_date_override')
            if override_date_str:
                try:
                    parts = override_date_str.split('-')
                    effective_date_json = json.dumps({
                        'year': int(parts[0]),
                        'month': int(parts[1]) - 1,
                        'day': int(parts[2])
                    })
                except:
                    pass
        
        return {'effective_date_json': effective_date_json}

    return app

app = create_app()
print("Hi 1")

if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('REPLIT_DEV_DOMAIN') is not None
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)

