import os
from flask import Flask, session, current_app
from flask_session import Session
from app.config import Config
from app.modules.registry import get_visible_nav


def create_app() -> Flask:
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')
    app.config.from_object(Config)

    # Ensure session directory exists
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    Session(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.blueprints.auth      import bp as auth_bp
    from app.blueprints.dashboard import bp as dashboard_bp
    from app.blueprints.settings  import bp as settings_bp
    from app.blueprints.todos     import bp as todos_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(todos_bp)

    # ── Template context ──────────────────────────────────────────────────────
    @app.context_processor
    def inject_nav():
        """Make nav and user available in every template."""
        return {
            'nav':  get_visible_nav(app.config, session),
            'user': session.get('user', {}),
        }

    return app
