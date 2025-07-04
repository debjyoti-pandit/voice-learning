from flask import Blueprint, render_template

# Blueprint serving simple HTML pages
templates_bp = Blueprint('templates', __name__)


@templates_bp.route('/')
def index():
    return render_template('index.html')


@templates_bp.route('/dialer')
def dialer():
    return render_template('dialer.html') 