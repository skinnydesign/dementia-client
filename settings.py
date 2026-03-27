from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app, jsonify)
from app.wifi.manager import scan_networks, connect_network, disconnect_network, get_current_connection
from app.modules.registry import get_available_modules, get_visible_nav, AVAILABLE_MODULES
from app.api.client import get_client, APIError

bp = Blueprint('settings', __name__, url_prefix='/settings')


def _require_login():
    if not session.get('api_token'):
        return redirect(url_for('auth.login'))


@bp.route('/')
def index():
    redir = _require_login()
    if redir: return redir

    nav              = get_visible_nav(current_app.config, session)
    available        = get_available_modules()
    config_enabled   = current_app.config.get('ENABLED_MODULES', [])
    hidden_modules   = set(session.get('hidden_modules', []))
    current_wifi     = get_current_connection()

    return render_template('settings/index.html',
        nav=nav,
        available_modules=available,
        config_enabled=config_enabled,
        hidden_modules=hidden_modules,
        current_wifi=current_wifi,
        user=session.get('user', {}),
    )


# ── WiFi ─────────────────────────────────────────────────────────────────────

@bp.route('/wifi/scan')
def wifi_scan():
    """AJAX endpoint — returns network list as JSON."""
    redir = _require_login()
    if redir: return jsonify({'error': 'Not logged in'}), 401

    networks, error = scan_networks()

    return jsonify({
        'error':    error,
        'networks': [
            {
                'ssid':     n.ssid,
                'signal':   n.signal,
                'bars':     n.signal_bars,
                'security': n.security,
                'in_use':   n.in_use,
            }
            for n in networks
        ]
    })


@bp.route('/wifi/connect', methods=['POST'])
def wifi_connect():
    redir = _require_login()
    if redir: return redir

    ssid     = request.form.get('ssid', '').strip()
    password = request.form.get('password', '').strip() or None

    if not ssid:
        flash('SSID is required.', 'error')
        return redirect(url_for('settings.index'))

    success, message = connect_network(ssid, password)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('settings.index'))


@bp.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    redir = _require_login()
    if redir: return redir

    success, message = disconnect_network()
    flash(message, 'success' if success else 'error')
    return redirect(url_for('settings.index'))


# ── Module visibility ─────────────────────────────────────────────────────────

@bp.route('/modules/toggle', methods=['POST'])
def toggle_module():
    redir = _require_login()
    if redir: return redir

    slug   = request.form.get('slug', '').strip()
    action = request.form.get('action', '')   # 'hide' or 'show'

    valid_slugs = {m['slug'] for m in AVAILABLE_MODULES}
    if slug not in valid_slugs:
        flash('Unknown module.', 'error')
        return redirect(url_for('settings.index'))

    hidden = set(session.get('hidden_modules', []))

    if action == 'hide':
        hidden.add(slug)
        flash(f'Module hidden.', 'info')
    elif action == 'show':
        hidden.discard(slug)
        flash(f'Module shown.', 'success')

    session['hidden_modules'] = list(hidden)
    return redirect(url_for('settings.index'))


# ── Account ───────────────────────────────────────────────────────────────────

@bp.route('/account/logout', methods=['POST'])
def account_logout():
    try:
        if session.get('api_token'):
            get_client().revoke_token()
    except Exception:
        pass
    session.clear()
    flash('Logged out and token revoked.', 'info')
    return redirect(url_for('auth.login'))
