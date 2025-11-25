from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
import json
import os

# Load .flaskenv before creating the app
from dotenv import load_dotenv
import os as _os
_flaskenv_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), '.flaskenv')
load_dotenv(_flaskenv_path)

app = Flask(__name__)

# Apply ProxyFix if Nexus is behind another reverse proxy (e.g., nginx, cloudflare)
# This ensures correct client IP detection for rate limiting and logging
# Set BEHIND_PROXY=true in .flaskenv if using an external reverse proxy
if os.environ.get('BEHIND_PROXY', 'false').lower() in ('true', '1', 'yes'):
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,      # Trust X-Forwarded-For
        x_proto=1,    # Trust X-Forwarded-Proto
        x_host=1,     # Trust X-Forwarded-Host
        x_prefix=1    # Trust X-Forwarded-Prefix
    )

# Configure rate limiting (higher limits for gateway service)
from flask_limiter import Limiter
from app.rate_limit_key import get_user_id_or_ip

limiter = Limiter(
    app=app,
    key_func=get_user_id_or_ip,  # Per-user rate limiting
    default_limits=["20000 per hour", "1000 per minute"],  # Higher limits for gateway on local LAN
    storage_uri="memory://"
)

# Explicitly load the secret key from the environment variables loaded from .flaskenv
# This is crucial for session management.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("A SECRET_KEY must be set in the .flaskenv file.")

# Session cookie security settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

# Disable static file caching in development
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # No caching for static files

# Configure logging level from environment
import logging
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
app.logger.setLevel(getattr(logging, log_level, logging.INFO))

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)

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

from app.version import VERSION, SERVICE_NAME as VERSION_SERVICE_NAME

# Context processor to inject version into all templates
@app.context_processor
def inject_version():
    return {
        'app_version': VERSION,
        'app_service_name': VERSION_SERVICE_NAME
    }

# Register RFC 7807 error handlers for consistent API error responses
from app.error_responses import (
    internal_server_error,
    not_found,
    bad_request,
    unauthorized,
    forbidden,
    service_unavailable
)

@app.errorhandler(400)
def handle_bad_request(e):
    """Handle 400 Bad Request errors"""
    return bad_request(detail=str(e))

@app.errorhandler(401)
def handle_unauthorized(e):
    """Handle 401 Unauthorized errors"""
    return unauthorized(detail=str(e))

@app.errorhandler(403)
def handle_forbidden(e):
    """Handle 403 Forbidden errors"""
    return forbidden(detail=str(e))

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 Not Found errors"""
    return not_found(detail=str(e))

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle 500 Internal Server Error"""
    app.logger.error(f"Internal server error: {e}")
    return internal_server_error()

@app.errorhandler(503)
def handle_service_unavailable(e):
    """Handle 503 Service Unavailable errors"""
    return service_unavailable(detail=str(e))

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catch-all handler for unexpected exceptions"""
    app.logger.exception(f"Unexpected error: {e}")
    return internal_server_error(detail="An unexpected error occurred")

# Configure OpenAPI/Swagger documentation
from flasgger import Swagger

swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": f"{app.config.get('SERVICE_NAME', 'HiveMatrix')} API",
        "description": "API documentation for HiveMatrix Nexus - HTTPS gateway and authentication proxy",
        "version": VERSION
    },
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT Authorization header using the Bearer scheme. Example: 'Authorization: Bearer {token}'"
        }
    },
    "security": [
        {
            "Bearer": []
        }
    ]
}

Swagger(app, config=swagger_config, template=swagger_template)

from app import routes

# Log service startup
helm_logger.info(f"{app.config['SERVICE_NAME']} service started")
