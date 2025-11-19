from flask import Flask
import json
import os

# Load .flaskenv before creating the app
from dotenv import load_dotenv
import os as _os
_flaskenv_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), '.flaskenv')
load_dotenv(_flaskenv_path)

app = Flask(__name__)

# Explicitly load the secret key from the environment variables loaded from .flaskenv
# This is crucial for session management.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("A SECRET_KEY must be set in the .flaskenv file.")

# Session cookie security settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

# Load other configuration variables
app.config['CORE_SERVICE_URL'] = os.environ.get('CORE_SERVICE_URL')
app.config['NEXUS_SERVICE_URL'] = os.environ.get('NEXUS_SERVICE_URL', 'http://localhost:8000')


# Load services configuration from services.json
try:
    with open('services.json') as f:
        services_config = json.load(f)
        app.config['SERVICES'] = services_config
except FileNotFoundError:
    print("WARNING: services.json not found. The proxy will not know about any backend services.")
    app.config['SERVICES'] = {}

# Initialize Helm logger for centralized logging
app.config['SERVICE_NAME'] = os.environ.get('SERVICE_NAME', 'nexus')
app.config['HELM_SERVICE_URL'] = os.environ.get('HELM_SERVICE_URL', 'http://localhost:5004')

from app.helm_logger import init_helm_logger
helm_logger = init_helm_logger(
    app.config['SERVICE_NAME'],
    app.config['HELM_SERVICE_URL']
)

from app import routes

# Log service startup
helm_logger.info(f"{app.config['SERVICE_NAME']} service started")
