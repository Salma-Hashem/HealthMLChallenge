"""
Flask application factory for the Care Coordinator Assistant.

Usage in main.py:
    app = create_app(db)
"""

import os
from flask import Flask

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")


def create_app(db: dict) -> Flask:
    """Create the Flask app, wire blueprints, and inject the shared DB.

    Args:
        db: In-memory database from data.loader.load_all_data().

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__, static_folder=os.path.abspath(FRONTEND_DIST), static_url_path="")

    app.config["db"] = db

    from api.routes.misc import misc_bp
    from api.routes.patients import patients_bp
    from api.routes.providers import providers_bp
    from api.routes.scheduling import scheduling_bp
    from api.routes.insurance import insurance_bp
    from api.routes.chat import chat_bp

    app.register_blueprint(misc_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(scheduling_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(chat_bp)

    return app
