from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app)
from app.api.client import get_client, APIError

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('api_token'):
        return redirect(url_for('dashboard.index'))

    error = None

    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            error = 'Email and password are required.'
        else:
            try:
                client = get_client()
                data   = client.login(email, password)

                # Check subscription — API returns 402 if not subscribed
                session['api_token'] = data['token']
                session['user']      = data['user']
                session.permanent    = False

                flash('Logged in successfully.', 'success')
                return redirect(url_for('dashboard.index'))

            except APIError as e:
                if e.status_code == 402:
                    error = 'Your account does not have an active subscription. Please subscribe at the main app.'
                elif e.status_code == 422:
                    error = 'Invalid email or password.'
                else:
                    error = str(e)
            except Exception as e:
                error = f'Could not reach the server: {e}'

    return render_template('auth/login.html', error=error)


@bp.route('/logout', methods=['POST'])
def logout():
    try:
        if session.get('api_token'):
            get_client().revoke_token()
    except Exception:
        pass

    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('auth.login'))
