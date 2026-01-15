import stripe
import os
from flask import flash, Blueprint, jsonify, request, current_app, url_for, render_template
from flask_login import login_required, current_user
from extensions import db
import logging
from flask import redirect, url_for, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user


from models import SubscriptionMetrics

PROMO_PRICE_ID = 'price_promo_99cents'
STANDARD_PRICE_ID = 'price_1Q0CJT08Qtnm286sGfkBQ3C0'
PROMO_SUBSCRIBER_LIMIT = 50

def create_payments_blueprint(db):
    payments = Blueprint('payments', __name__)

    print("Hi 1")

    @login_required
    @payments.route('/create-checkout-session', methods=['POST'])
    def create_checkout_session():
        print("hi - 1")
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

        print("authenticate laptop", current_user.is_authenticated)

        if not current_user.is_authenticated:
            print("not authenticate")
            return redirect(url_for(
                'auth.login'))
        print("hi - 2")
        try:
            print("hi - 3")
            
            promo_count = SubscriptionMetrics.get_promo_subscriber_count()
            use_promo = promo_count < PROMO_SUBSCRIBER_LIMIT
            
            if use_promo:
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product': 'prod_premium_attorney',
                            'unit_amount': 99,
                            'recurring': {
                                'interval': 'month',
                                'interval_count': 1
                            }
                        },
                        'quantity': 1,
                    }],
                    mode='subscription',
                    subscription_data={
                        'metadata': {'promo_first_month': 'true'}
                    },
                    success_url=url_for('payments.payment_success', _external=True)
                    + '?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url=url_for('payments.payment_cancel', _external=True),
                    client_reference_id=str(current_user.id),
                )
            else:
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price': STANDARD_PRICE_ID,
                        'quantity': 1,
                    }],
                    mode='subscription',
                    success_url=url_for('payments.payment_success', _external=True)
                    + '?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url=url_for('payments.payment_cancel', _external=True),
                    client_reference_id=str(current_user.id),
                )
            
            print("session created successfully", session['url'],
                  session['id'])
            print("hi - 4")
            return jsonify({'sessionId': session['url']})

        except stripe.error.CardError as e:
            print("hi - 5")
            print(f"Stripe card error: {e}")
            return jsonify(error=e.user_message), 402

        except stripe.error.RateLimitError as e:
            # Too many requests to the API too quickly
            print(f"Stripe rate limit error: {e.user_message}")
            return jsonify(
                error="Rate limit error, please try again later."), 429

        except stripe.error.InvalidRequestError as e:
            # Invalid parameters were supplied to Stripe's API
            print(f"Stripe invalid request error: {e.user_message}")
            return jsonify(
                error="Invalid request, please check the parameters."), 400

        except stripe.error.AuthenticationError as e:
            # Authentication with Stripe's API failed (incorrect API key?)
            print(f"Stripe authentication error: {e.user_message}")
            return jsonify(error="Authentication error with Stripe."), 401

        except stripe.error.APIConnectionError as e:
            # Network communication with Stripe failed
            print(f"Stripe API connection error: {e}")
            return jsonify(
                error=
                "Network communication with Stripe failed, please try again."
            ), 502

        except stripe.error.StripeError as e:
            # Generic Stripe error handler
            print(f"Stripe general error: {e.user_message}")
            return jsonify(
                error="A Stripe error occurred, please try again."), 500

        except Exception as e:
            # Catch any other exceptions (non-Stripe related)
            print(f"Unexpected error: {str(e)}")
            current_app.logger.error(
                f"Unexpected error creating checkout session: {str(e)}")
            return jsonify(
                error="An unexpected error occurred. Please try again later."
            ), 500

    @login_required
    @payments.route('/create-checkout-session_1', methods=['POST'])
    def create_checkout_session1():
        print("hi hi-2")
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        print("authenticate laptop", current_user.is_authenticated)

        if not current_user.is_authenticated:
            print("not authenticate")
            return redirect(url_for(
                'auth.login'))  # Redirect to login page if not authenticated

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product': 'prod_R79VAO4wDGcMLk',
                        'unit_amount': 5000,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('payments.payment_success_1',
                                    _external=True) +
                '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('payments.payment_cancel', _external=True),
                client_reference_id=str(
                    current_user.id),  # Safe to use after authentication
            )
            print("session 1", session['url'], session['id'])
            return jsonify({'sessionId': session['url']})
        except stripe.error.StripeError as e:
            current_app.logger.error(f"Stripe error: {str(e)}")
            return jsonify(error=str(e)), 403
        except Exception as e:
            current_app.logger.error(
                f"Unexpected error creating checkout session: {str(e)}")
            return jsonify(
                error="An unexpected error occurred. Please try again later."
            ), 500

    @payments.route('/payment_success_1')
    @login_required
    def payment_success_1():
        """Handle one-time token purchase success (not a subscription)."""
        session_id = request.args.get('session_id')
        if not session_id:
            return "Invalid session ID", 400

        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid" and str(
                    session.client_reference_id) == str(current_user.id):
                current_user.token += 10
                if session.customer:
                    current_user.stripe_customer_id = session.customer
                db.session.commit()
                return render_template('payment_success1.html')
            else:
                raise Exception("Payment verification failed")
        except Exception as e:
            current_app.logger.error(f"Error verifying payment: {str(e)}")
            return "Payment verification failed. Please contact support.", 400

    @payments.route('/payment_success')
    @login_required
    def payment_success():
        session_id = request.args.get('session_id')
        if not session_id:
            return "Invalid session ID", 400

        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        try:
            session = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
            if session.payment_status == "paid" and str(
                    session.client_reference_id) == str(current_user.id):
                current_user.subscription_type = 'paid'
                current_user.stripe_customer_id = session.customer
                subscription = session.subscription
                if hasattr(subscription, 'id'):
                    current_user.stripe_subscription_id = subscription.id
                else:
                    current_user.stripe_subscription_id = subscription
                
                is_promo = False
                if subscription and hasattr(subscription, 'metadata'):
                    is_promo = subscription.metadata.get('promo_first_month') == 'true'
                
                if is_promo:
                    SubscriptionMetrics.increment_promo_subscribers()
                
                db.session.commit()
                return render_template('payment_success.html')
            else:
                raise Exception("Payment verification failed")
        except Exception as e:
            current_app.logger.error(f"Error verifying payment: {str(e)}")
            return "Payment verification failed. Please contact support.", 400

    @payments.route('/payment_cancel')
    @login_required
    def payment_cancel():
        try:

            customers = stripe.Customer.list(email=current_user.email)
            if customers.data:
                customer = customers.data[0]
                subscriptions = stripe.Subscription.list(customer=customer.id)

                if subscriptions.data:
                    subscription = subscriptions.data[0]

                    stripe.Subscription.delete(subscription.id)
                    current_user.subscription_type = 'free'
                    db.session.commit()
                    flash('Your subscription has been canceled.', 'success')
                else:
                    flash('No active subscription found.', 'warning')
            else:
                flash('Stripe customer not found.', 'danger')

        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'danger')

        return render_template('payment_cancel.html')

    @payments.route('/stripe-webhook', methods=['POST'])
    def stripe_webhook():
        """Handle Stripe webhook events to keep subscription status in sync."""
        from models import User
        import logging
        
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        payload = request.get_data()
        sig_header = request.headers.get('Stripe-Signature')
        
        try:
            if webhook_secret:
                event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
            else:
                event = stripe.Event.construct_from(
                    request.get_json(), stripe.api_key
                )
        except ValueError as e:
            logging.error(f"Invalid webhook payload: {e}")
            return jsonify(error="Invalid payload"), 400
        except stripe.error.SignatureVerificationError as e:
            logging.error(f"Invalid webhook signature: {e}")
            return jsonify(error="Invalid signature"), 400
        
        event_type = event['type']
        data = event['data']['object']
        
        logging.info(f"Received Stripe webhook: {event_type}")
        
        if event_type == 'customer.subscription.deleted':
            subscription_id = data.get('id')
            customer_id = data.get('customer')
            
            user = User.query.filter(
                (User.stripe_subscription_id == subscription_id) | 
                (User.stripe_customer_id == customer_id)
            ).first()
            
            if user:
                user.subscription_type = 'free'
                user.stripe_subscription_id = None
                db.session.commit()
                logging.info(f"Subscription canceled for user {user.id} ({user.email})")
        
        elif event_type == 'customer.subscription.updated':
            subscription_id = data.get('id')
            customer_id = data.get('customer')
            status = data.get('status')
            
            user = User.query.filter(
                (User.stripe_subscription_id == subscription_id) | 
                (User.stripe_customer_id == customer_id)
            ).first()
            
            if user:
                if status in ['active', 'trialing']:
                    user.subscription_type = 'paid'
                    user.stripe_subscription_id = subscription_id
                    user.stripe_customer_id = customer_id
                elif status in ['canceled', 'unpaid', 'past_due']:
                    user.subscription_type = 'free'
                    if status == 'canceled':
                        user.stripe_subscription_id = None
                db.session.commit()
                logging.info(f"Subscription updated for user {user.id}: status={status}")
        
        elif event_type == 'invoice.payment_failed':
            customer_id = data.get('customer')
            
            user = User.query.filter_by(stripe_customer_id=customer_id).first()
            
            if user:
                user.subscription_type = 'free'
                db.session.commit()
                logging.info(f"Payment failed for user {user.id} ({user.email})")
        
        elif event_type == 'checkout.session.completed':
            session = data
            customer_id = session.get('customer')
            subscription_id = session.get('subscription')
            client_ref_id = session.get('client_reference_id')
            
            if client_ref_id:
                user = User.query.get(int(client_ref_id))
                if user:
                    user.stripe_customer_id = customer_id
                    user.stripe_subscription_id = subscription_id
                    user.subscription_type = 'paid'
                    db.session.commit()
                    logging.info(f"Checkout completed for user {user.id}")
        
        return jsonify(success=True), 200

    return payments
