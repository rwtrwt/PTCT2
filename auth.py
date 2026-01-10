from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, GuestToken
from extensions import db
from urllib.parse import urlparse, urljoin
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from flask import current_app as app
from extensions import mail  # Assuming you've initialized Flask-Mail as `mail`
import os
import stripe

auth = Blueprint('auth', __name__)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http',
                               'https') and ref_url.netloc == test_url.netloc

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user:
            # Check Stripe subscription status (skip if no API key configured)
            stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
            if stripe.api_key:
                try:
                    customers = stripe.Customer.list(email=user.email)
                    print("user.email",user.email)
                    print("customers",customers)

                    user.subscription_type = 'free'

                    if customers.data:
                        customer = customers.data[0]  # Get the first matching customer
                        subscriptions = stripe.Subscription.list(customer=customer.id, status='active')

                        # If an active subscription exists, set subscription_type to 'paid'
                        if subscriptions.data:
                            user.subscription_type = 'paid'

                    db.session.commit()
                except Exception as e:
                    print(f"Stripe check skipped: {e}")
            else:
                print("Stripe API key not configured - skipping subscription check")
                
        if user and user.check_password(password):
            
            if not user.confirmed:
                flash('Account is not confirmed. Please check your email for confirmation.')
                return redirect(url_for('auth.login'))
            
            if hasattr(user, 'is_blocked') and user.is_blocked:
                flash('Your account has been blocked. Please contact support.')
                return redirect(url_for('auth.login'))

            login = login_user(user)
            print("login",login)
            
            next_page = request.args.get('next')
            if not next_page or not is_safe_url(next_page):
                next_page = url_for('main.dashboard')
            return redirect(next_page)
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')



def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return serializer.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])

def confirm_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=expiration)
    except:
        return False
    return email

def send_verification_email(user_email):
    token = generate_confirmation_token(user_email)
    confirm_url = url_for('auth.confirm_email', token=token, _external=True)
    html = render_template('activate.html', confirm_url=confirm_url)
    subject = "Please confirm your email"
    msg = Message(subject=subject, recipients=[user_email], html=html)
    mail.send(msg)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        elif User.query.filter_by(email=email).first():
            flash('Email already exists')
        else:
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            new_user.confirmed = False  # User is not confirmed yet
            db.session.add(new_user)
            db.session.commit()
            
            ip_address = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '0.0.0.0'
            guests = GuestToken.query.filter(
                (GuestToken.email == email) | (GuestToken.ip_address == ip_address)
            ).all()
            for guest in guests:
                if not guest.linked_user_id:
                    guest.linked_user_id = new_user.id
            db.session.commit()

            # Send confirmation email
            send_verification_email(new_user.email)

            flash('A confirmation email has been sent to your email address.')
            return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = confirm_token(token)
    except:
        flash('The confirmation link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()
    if user.confirmed:
        flash('Account already confirmed. Please log in.', 'success')
    else:
        user.confirmed = True
        db.session.commit()
        flash('You have confirmed your account. Thanks!', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))



from itsdangerous import URLSafeTimedSerializer
from flask import current_app

@auth.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # Initialize serializer inside the function
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # Generate a password reset token
            token = s.dumps(email, salt=current_app.config['SECURITY_PASSWORD_SALT'])
            # Send the email
            reset_url = url_for('auth.reset_with_token', token=token, _external=True)
            msg = Message('Password Reset Request',
                          sender=current_app.config['MAIL_DEFAULT_SENDER'],
                          recipients=[email])
            msg.body = f'Your link to reset your password is: {reset_url}'
            mail.send(msg)
            flash('A password reset link has been sent to your email.')
            return redirect(url_for('auth.login'))
        else:
            flash('Email not found')
    return render_template('reset_password.html')

@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_with_token(token):
    # Initialize serializer inside the function
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    
    try:
        email = s.loads(token, salt=current_app.config['SECURITY_PASSWORD_SALT'], max_age=3600)  
    except:
        flash('The reset link is invalid or has expired.')
        return redirect(url_for('auth.reset_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(new_password)
            db.session.commit()
            flash('Your password has been updated!')
            return redirect(url_for('auth.login'))

    return render_template('reset_with_token.html')
