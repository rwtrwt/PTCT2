from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, GuestToken, GovernmentDomain, GovernmentRegistrationRequest
from extensions import db
from urllib.parse import urlparse, urljoin
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from flask import current_app as app
from extensions import mail
import os
import stripe
import secrets
from datetime import datetime

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
            # IMPORTANT: Preserve government subscription type - do not overwrite
            stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
            if stripe.api_key and user.subscription_type != 'government':
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
                if user.subscription_type == 'government':
                    print("Government user - preserving subscription status")
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

def send_government_verification_email(user, email_domain, verification_token):
    """Send email to admin for government account verification."""
    approve_url = url_for('auth.verify_government', token=verification_token, action='approve', _external=True)
    deny_url = url_for('auth.verify_government', token=verification_token, action='deny', _external=True)
    
    html = f"""
    <h2>Government Account Verification Request</h2>
    <p>A user has requested government account access:</p>
    <ul>
        <li><strong>Username:</strong> {user.username}</li>
        <li><strong>Email:</strong> {user.email}</li>
        <li><strong>Email Domain:</strong> {email_domain}</li>
    </ul>
    <p>Please verify that this email domain belongs to a legitimate government entity.</p>
    <p>
        <a href="{approve_url}" style="display: inline-block; padding: 12px 24px; background: #22c55e; color: white; text-decoration: none; border-radius: 6px; margin-right: 10px;">Approve</a>
        <a href="{deny_url}" style="display: inline-block; padding: 12px 24px; background: #ef4444; color: white; text-decoration: none; border-radius: 6px;">Deny</a>
    </p>
    <p><small>Approving this request will also approve the domain ({email_domain}) for future automatic approvals.</small></p>
    """
    
    subject = f"Government Account Verification Request: {email_domain}"
    msg = Message(subject=subject, recipients=['russell@danielstaylor.com'], html=html)
    mail.send(msg)


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        is_government = request.form.get('is_government') == 'on'
        government_oath = request.form.get('government_oath') == 'on'

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        elif User.query.filter_by(email=email).first():
            flash('Email already exists')
        elif is_government and not government_oath:
            flash('You must accept the oath to register as a government employee.')
        else:
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            new_user.confirmed = False
            new_user.is_government = is_government
            new_user.government_oath_accepted = government_oath if is_government else False
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
            
            if is_government:
                email_domain = email.split('@')[1].lower()
                approved_domain = GovernmentDomain.query.filter_by(domain=email_domain, approved=True).first()
                
                if approved_domain:
                    new_user.government_verified = True
                    new_user.subscription_type = 'government'
                    db.session.commit()
                    flash('Your government account has been automatically verified!')
                else:
                    verification_token = secrets.token_urlsafe(32)
                    gov_request = GovernmentRegistrationRequest(
                        user_id=new_user.id,
                        email_domain=email_domain,
                        status='pending',
                        verification_token=verification_token
                    )
                    db.session.add(gov_request)
                    db.session.commit()
                    
                    try:
                        send_government_verification_email(new_user, email_domain, verification_token)
                    except Exception as e:
                        print(f"Failed to send government verification email: {e}")
                    
                    flash('Your government account request has been submitted for verification. You will be notified once approved.')

            send_verification_email(new_user.email)

            flash('A confirmation email has been sent to your email address.')
            return redirect(url_for('auth.login'))
    return render_template('register.html')


@auth.route('/verify-government/<token>')
def verify_government(token):
    """Handle government account verification approve/deny."""
    action = request.args.get('action')
    
    gov_request = GovernmentRegistrationRequest.query.filter_by(verification_token=token).first()
    
    if not gov_request:
        flash('Invalid or expired verification link.')
        return redirect(url_for('main.home'))
    
    if gov_request.status != 'pending':
        flash(f'This request has already been {gov_request.status}.')
        return redirect(url_for('main.home'))
    
    user = User.query.get(gov_request.user_id)
    
    if action == 'approve':
        gov_request.status = 'approved'
        gov_request.reviewed_at = datetime.utcnow()
        gov_request.reviewed_by = 'admin'
        
        existing_domain = GovernmentDomain.query.filter_by(domain=gov_request.email_domain).first()
        if not existing_domain:
            new_domain = GovernmentDomain(
                domain=gov_request.email_domain,
                approved=True,
                approved_by='admin'
            )
            db.session.add(new_domain)
        
        if user:
            user.government_verified = True
            user.subscription_type = 'government'
        
        db.session.commit()
        
        try:
            msg = Message(
                subject="Your Government Account Has Been Approved",
                recipients=[user.email],
                html=f"""
                <h2>Government Account Approved</h2>
                <p>Your government account for the Georgia Parenting Time Calendar Tool has been approved.</p>
                <p>You now have free access to all features. Please log in to access your account.</p>
                """
            )
            mail.send(msg)
        except Exception as e:
            print(f"Failed to send approval notification: {e}")
        
        flash('Government account has been approved. The domain has been saved for future automatic approvals.')
        
    elif action == 'deny':
        gov_request.status = 'denied'
        gov_request.reviewed_at = datetime.utcnow()
        gov_request.reviewed_by = 'admin'
        db.session.commit()
        
        try:
            msg = Message(
                subject="Government Account Request Denied",
                recipients=[user.email],
                html=f"""
                <h2>Government Account Request Denied</h2>
                <p>Your request for a government account for the Georgia Parenting Time Calendar Tool has been denied.</p>
                <p>If you believe this is an error, please contact support.</p>
                """
            )
            mail.send(msg)
        except Exception as e:
            print(f"Failed to send denial notification: {e}")
        
        flash('Government account request has been denied.')
    
    return redirect(url_for('main.home'))

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
