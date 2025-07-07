from flask import Blueprint, render_template, current_app

templates_bp = Blueprint('templates', __name__)

@templates_bp.route('/')
def index():
    current_app.logger.info("🖼️ index route invoked")
    current_app.logger.info("🖼️ index route processing complete")
    return render_template('index.html')

@templates_bp.route('/second-dialer')
def dialer():
    current_app.logger.info("🖼️ dialer route invoked")
    current_app.logger.info("🖼️ dialer route processing complete")
    return render_template('dialer.html')
