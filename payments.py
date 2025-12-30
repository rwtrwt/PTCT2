import stripe
import os
from flask import flash, Blueprint, jsonify, request, current_app, url_for, render_template
from flask_login import login_required, current_user
from extensions import db
import logging
from flask import redirect, url_for, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user


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
                'auth.login'))  # Redirect to login page if not authenticated
        print("hi - 2")
        try:
            print("hi - 3")
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': 'price_1Q0CJT08Qtnm286sGfkBQ3C0',  # Your Stripe price ID
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=url_for('payments.payment_success', _external=True)
                + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('payments.payment_cancel', _external=True),
                client_reference_id=str(
                    current_user.id),  # Reference the current user
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
        session_id = request.args.get('session_id')
        if not session_id:
            return "Invalid session ID", 400

        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid" and str(
                    session.client_reference_id) == str(current_user.id):
                current_user.token += 10
                current_user.stripe_subscription_id = session.subscription
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
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid" and str(
                    session.client_reference_id) == str(current_user.id):
                current_user.subscription_type = 'paid'
                current_user.stripe_subscription_id = session.subscription
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

    return payments
