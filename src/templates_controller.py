from flask import Blueprint, current_app, render_template

from src.constants import NAME

templates_bp = Blueprint("templates", __name__)


@templates_bp.route("/")
def index():
    current_app.logger.info("🖼️ index route invoked")
    current_app.logger.info("🖼️ index route processing complete")
    return render_template("index.html", default_name=NAME)


@templates_bp.route("/dialer")
def dialer():
    return render_template("dialer.html", default_name=NAME)
