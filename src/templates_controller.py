from flask import Blueprint, render_template

templates_bp = Blueprint('templates', __name__)

@templates_bp.route('/')
def index():
    return render_template('index.html')

@templates_bp.route('/second-dialer')
def dialer():
    return render_template('dialer.html')
