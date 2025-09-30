import requests
from flask import request, Response, url_for, session, redirect, current_app
from app import app
from bs4 import BeautifulSoup
import jwt

# Cache for Core's public key to avoid fetching it on every request
jwks_client = None

def get_jwks_client():
    """Initializes and returns the JWKS client."""
    global jwks_client
    if jwks_client is None:
        core_url = current_app.config['CORE_SERVICE_URL']
        jwks_client = jwt.PyJWKClient(f"{core_url}/.well-known/jwks.json")
    return jwks_client

def validate_token(token):
    """
    Validates a JWT token and returns the decoded data.
    Returns None if the token is invalid or expired.
    """
    try:
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer="hivematrix.core",
            options={"verify_exp": True}
        )
        return data
    except jwt.ExpiredSignatureError:
        # Token has expired
        return None
    except jwt.PyJWTError:
        # Token is invalid for other reasons
        return None

@app.route('/auth-callback')
def auth_callback():
    """
    Callback route for after Core authenticates a user.
    It receives the HiveMatrix JWT, validates it, and sets the local session.
    This route MUST remain public.
    """
    token = request.args.get('token')
    if not token:
        return "Authentication failed: No token provided.", 400

    data = validate_token(token)
    if not data:
        return "Authentication failed: Invalid or expired token.", 401

    session['token'] = token
    session['user'] = data

    # Redirect to the originally requested path
    return redirect(session.pop('next_url', '/'))


@app.route('/logout')
def logout():
    """
    Clears the user's session and redirects to Core's logout.
    """
    session.clear()
    core_url = current_app.config['CORE_SERVICE_URL']
    return redirect(f"{core_url}/logout")


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def main_gateway(path):
    """
    This is the single entry point for all user-facing requests.
    It handles authentication, token validation, and proxying to services.
    """
    # --- Check if user has a token ---
    if 'token' not in session:
        # No token at all - redirect to login
        session['next_url'] = request.full_path
        nexus_callback_url = url_for('auth_callback', _external=True)
        core_login_url = f"{current_app.config['CORE_SERVICE_URL']}/login?next={nexus_callback_url}"
        return redirect(core_login_url)

    # --- Validate the token ---
    token = session['token']
    token_data = validate_token(token)

    if not token_data:
        # Token is expired or invalid - clear session and redirect to login
        session.clear()
        session['next_url'] = request.full_path
        nexus_callback_url = url_for('auth_callback', _external=True)
        core_login_url = f"{current_app.config['CORE_SERVICE_URL']}/login?next={nexus_callback_url}"
        return redirect(core_login_url)

    # Update session with fresh token data (in case it was decoded again)
    session['user'] = token_data

    # If the path is empty, redirect to the first available service
    if not path:
        services = current_app.config.get('SERVICES', {})
        if services:
            first_service = next(iter(services))
            return redirect(f'/{first_service}/')
        else:
            return "<h1>HiveMatrix Nexus</h1><p>No services configured.</p>", 200

    # Determine service from the first part of the path
    path_parts = path.split('/')
    service_name = path_parts[0]
    service_path = '/'.join(path_parts[1:])

    services = current_app.config.get('SERVICES', {})
    service_config = services.get(service_name)

    if not service_config:
        return f"Service '{service_name}' not found.", 404

    backend_url = f"{service_config['url']}/{service_path}"

    # --- Add Auth Header to Proxied Request ---
    headers = {key: value for (key, value) in request.headers if key != 'Host'}
    headers['Authorization'] = f"Bearer {token}"

    try:
        resp = requests.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False)

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.raw.headers.items() if name.lower() not in excluded_headers]
        content = resp.content

        if 'text/html' in resp.headers.get('Content-Type', ''):
            soup = BeautifulSoup(content, 'html.parser')
            head = soup.find('head')
            if head:
                css_link = soup.new_tag('link', rel='stylesheet', href=url_for('static', filename='css/global.css'))
                head.append(css_link)
                content = str(soup)

        return Response(content, resp.status_code, headers)

    except requests.exceptions.RequestException as e:
        return f"Proxy error: {e}", 502
