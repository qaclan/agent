import os
import sys
import logging

from flask import Flask

from .routes.projects import bp as projects_bp
from .routes.features import bp as features_bp
from .routes.scripts import bp as scripts_bp
from .routes.suites import bp as suites_bp
from .routes.runs import bp as runs_bp
from .routes.envs import bp as envs_bp
from .routes.auth import bp as auth_bp


def _get_base_dir():
    """Resolve base directory for both normal and Nuitka onefile runs."""
    if getattr(sys, 'frozen', False):
        # Nuitka onefile: modules extracted to a temp dir
        return os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(__file__)


def create_app():
    # Configure logging for run diagnostics
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    static_dir = os.path.join(_get_base_dir(), 'static')
    app = Flask(__name__, static_folder=static_dir, static_url_path='')

    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp]:
        app.register_blueprint(bp)

    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    return app
