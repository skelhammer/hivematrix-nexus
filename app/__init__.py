from flask import Flask
import json
import os

app = Flask(__name__)

# Explicitly load the secret key from the environment variables loaded from .flaskenv
# This is crucial for session management.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("A SECRET_KEY must be set in the .flaskenv file.")

# Load other configuration variables
app.config['CORE_SERVICE_URL'] = os.environ.get('CORE_SERVICE_URL')


# Load services configuration from services.json
try:
    with open('services.json') as f:
        services_config = json.load(f)
        app.config['SERVICES'] = services_config
except FileNotFoundError:
    print("WARNING: services.json not found. The proxy will not know about any backend services.")
    app.config['SERVICES'] = {}


from app import routes
