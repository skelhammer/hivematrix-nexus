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
    Validates a JWT token by checking with Core.
    This ensures the session hasn't been revoked.
    Returns the decoded data if valid, None otherwise.
    """
    import requests

    try:
        # First verify signature locally
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer="hivematrix-core",
            options={"verify_exp": True}
        )

        # Then check with Core if session is still valid (not revoked)
        core_url = current_app.config['CORE_SERVICE_URL']
        try:
            validation_response = requests.post(
                f"{core_url}/api/token/validate",
                json={'token': token},
                timeout=2
            )

            if validation_response.status_code == 200:
                # Session is valid
                return data
            else:
                # Session revoked or invalid
                print(f"Token validation failed at Core: {validation_response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            # If Core is unreachable, fall back to local validation
            # This ensures the system keeps working even if Core is down
            print(f"Warning: Could not reach Core for validation: {e}")
            print("Falling back to local JWT validation")
            return data

    except jwt.ExpiredSignatureError:
        print("Token validation failed: Token expired")
        return None
    except jwt.PyJWTError as e:
        print(f"Token validation failed: {e}")
        return None

def inject_side_panel(soup, current_service):
    """Injects the side panel navigation into the HTML."""
    services = current_app.config.get('SERVICES', {})

    # Create side panel HTML
    side_panel_html = '''
    <div class="hivematrix-side-panel">
        <div class="side-panel__header">
            <h3 class="side-panel__title">HiveMatrix</h3>
        </div>
        <nav class="side-panel__nav">
            <ul class="side-panel__list">
    '''

    # Service icons mapping
    service_icons = {
        'template': '📝',
        'codex': '📚',
        'knowledgetree': '🌳',
        'ledger': '💰',
        'resolve': '🎫',
        'architect': '🏗️',
        'treasury': '💵',
        'core': '🔐',
        'nexus': '🌐',
        'helm': '⚙️'
    }

    # Add each service as a link
    for service_name, service_config in services.items():
        icon = service_icons.get(service_name, '📦')
        active_class = 'side-panel__item--active' if service_name == current_service else ''
        display_name = service_name.title()

        side_panel_html += f'''
            <li class="side-panel__item {active_class}">
                <a href="/{service_name}/" class="side-panel__link">
                    <span class="side-panel__icon">{icon}</span>
                    <span class="side-panel__label">{display_name}</span>
                </a>
            </li>
        '''

    side_panel_html += '''
            </ul>
        </nav>
        <div class="side-panel__footer">
            <a href="/logout" class="side-panel__link">
                <span class="side-panel__icon">🚪</span>
                <span class="side-panel__label">Logout</span>
            </a>
        </div>
    </div>
    '''

    # Add wrapper div for layout
    wrapper_start = '<div class="hivematrix-layout">'
    wrapper_end = '</div>'

    # Find body tag and inject
    body = soup.find('body')
    if body:
        # Wrap existing content
        body_contents = ''.join(str(tag) for tag in body.contents)
        body.clear()

        # Create new structure with proper nesting
        layout_wrapper = BeautifulSoup(f'''
        <div class="hivematrix-layout">
            {side_panel_html}
            <div class="hivematrix-content">
                {body_contents}
            </div>
        </div>
        ''', 'html.parser')

        body.append(layout_wrapper)

@app.route('/health')
def health():
    """
    Health check endpoint for monitoring.
    Returns 200 if service is running.
    """
    return {'status': 'healthy', 'service': 'nexus'}, 200


@app.route('/keycloak/', defaults={'path': ''})
@app.route('/keycloak/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def keycloak_proxy(path):
    """
    Proxy requests to Keycloak server.
    This allows external browsers to access Keycloak through Nexus's HTTPS endpoint.
    """
    import os
    import re

    # Use backend URL for proxy connection (always localhost:8080)
    # KEYCLOAK_SERVER_URL is the frontend URL that clients use
    keycloak_backend = os.environ.get('KEYCLOAK_BACKEND_URL', 'http://localhost:8080')
    keycloak_url = keycloak_backend
    backend_url = f"{keycloak_backend}/{path}"

    # Forward the request to Keycloak with proxy headers
    headers = {key: value for (key, value) in request.headers if key.lower() != 'host'}

    # Add X-Forwarded headers for Keycloak proxy detection
    headers['X-Forwarded-For'] = request.remote_addr
    headers['X-Forwarded-Proto'] = 'https' if request.is_secure else 'http'
    headers['X-Forwarded-Host'] = request.host
    headers['X-Forwarded-Port'] = '443'
    headers['X-Forwarded-Prefix'] = '/keycloak'

    try:
        resp = requests.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            data=request.get_data(),
            params=request.args,
            cookies=request.cookies,
            allow_redirects=False
        )

        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = []

        for name, value in resp.raw.headers.items():
            if name.lower() in excluded_headers:
                continue

            # Rewrite Set-Cookie headers to use the proxy path
            if name.lower() == 'set-cookie':
                # Remove domain restrictions and set path to /keycloak
                value = re.sub(r'; Domain=[^;]+', '', value)
                value = re.sub(r'; Path=[^;]+', '; Path=/keycloak', value)
                # Ensure SameSite=None for cross-origin cookies if using HTTPS
                if 'SameSite' not in value:
                    value += '; SameSite=Lax'

            response_headers.append((name, value))

        content = resp.content

        # Rewrite Location headers to go through Nexus proxy
        if resp.status_code in [301, 302, 303, 307, 308]:
            location = resp.headers.get('Location', '')
            if location.startswith(keycloak_url):
                # Rewrite to go through Nexus proxy
                new_location = location.replace(keycloak_url, request.host_url.rstrip('/') + '/keycloak')
                response_headers = [(name, new_location if name.lower() == 'location' else value)
                                  for (name, value) in response_headers]

        # Rewrite HTML/JS/CSS content to replace Keycloak URLs
        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' in content_type or 'application/javascript' in content_type or 'text/css' in content_type:
            try:
                text = content.decode('utf-8')
                # Replace absolute URLs to Keycloak with proxied URLs
                text = text.replace(keycloak_url, request.host_url.rstrip('/') + '/keycloak')
                # Replace relative references that might bypass the proxy
                text = re.sub(r'action="/', f'action="{request.host_url.rstrip("/")}/keycloak/', text)
                content = text.encode('utf-8')
            except:
                pass  # If decode/encode fails, just pass through original content

        return Response(content, resp.status_code, response_headers)

    except requests.exceptions.RequestException as e:
        return f"Keycloak proxy error: {e}", 502


@app.route('/login')
def login_proxy():
    """
    Initiates Keycloak login by building the authorization URL directly.
    This ensures external-facing URLs are used instead of localhost.
    """
    import os
    import secrets
    from urllib.parse import urlencode

    # Save where the user wanted to go
    session['next_url'] = request.args.get('next', '/')

    # Generate state and nonce for OIDC
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    session['oauth_nonce'] = nonce

    # Build Keycloak authorization URL using Nexus's proxy
    # This ensures external browsers can reach Keycloak through Nexus
    keycloak_realm = os.environ.get('KEYCLOAK_REALM', 'hivematrix')
    client_id = os.environ.get('KEYCLOAK_CLIENT_ID', 'core-client')

    # Nexus's callback URL (external-facing)
    redirect_uri = url_for('keycloak_callback', _external=True)

    # Build authorization URL using Nexus's /keycloak/ proxy path
    # This makes Keycloak accessible through the same external HTTPS endpoint
    nexus_keycloak_url = url_for('keycloak_proxy', path='', _external=True).rstrip('/')

    # Build authorization URL
    auth_params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce
    }

    keycloak_auth_url = f"{nexus_keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/auth"
    auth_url_with_params = f"{keycloak_auth_url}?{urlencode(auth_params)}"

    return redirect(auth_url_with_params)


@app.route('/keycloak-callback')
def keycloak_callback():
    """
    Keycloak redirects here after authentication.
    Exchange authorization code for tokens, then request JWT from Core.
    """
    import os

    # Check for errors from Keycloak
    error = request.args.get('error')
    if error:
        error_description = request.args.get('error_description', 'Unknown error')
        session.clear()
        return f"Authentication error: {error} - {error_description}", 401

    # Verify state to prevent CSRF
    state = request.args.get('state')
    if state != session.get('oauth_state'):
        session.clear()
        return "Invalid state parameter", 401

    # Get authorization code
    code = request.args.get('code')
    if not code:
        return "No authorization code received", 401

    # Exchange code for tokens with Keycloak
    # Use backend URL for server-to-server communication (avoids SSL issues)
    keycloak_backend = os.environ.get('KEYCLOAK_BACKEND_URL', 'http://localhost:8080')
    keycloak_realm = os.environ.get('KEYCLOAK_REALM', 'hivematrix')
    client_id = os.environ.get('KEYCLOAK_CLIENT_ID', 'core-client')
    client_secret = os.environ.get('KEYCLOAK_CLIENT_SECRET')
    redirect_uri = url_for('keycloak_callback', _external=True)

    token_url = f"{keycloak_backend}/realms/{keycloak_realm}/protocol/openid-connect/token"

    try:
        token_response = requests.post(
            token_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret
            }
        )

        if token_response.status_code != 200:
            return f"Failed to exchange code for token: {token_response.text}", 502

        token_data = token_response.json()
        access_token = token_data.get('access_token')

        # Now request JWT from Core by sending the access token
        core_url = current_app.config['CORE_SERVICE_URL']
        jwt_response = requests.post(
            f"{core_url}/api/token/exchange",
            headers={'Authorization': f'Bearer {access_token}'},
            json={'access_token': access_token}
        )

        if jwt_response.status_code == 200:
            jwt_token = jwt_response.json().get('token')
            if jwt_token:
                # Validate and store the token
                user_data = validate_token(jwt_token)
                if user_data:
                    session['token'] = jwt_token
                    session['user'] = user_data
                    session.pop('oauth_state', None)
                    session.pop('oauth_nonce', None)
                    # Redirect to original destination
                    return redirect(session.pop('next_url', '/'))

        return f"Failed to get JWT from Core: {jwt_response.status_code}", 502

    except requests.exceptions.RequestException as e:
        return f"Authentication flow error: {e}", 502




@app.route('/logout')
def logout():
    """
    Logout: revokes token at Core, clears session, and redirects to login.
    """
    from flask import make_response
    import requests

    # Get the token before clearing session
    token = session.get('token')

    # Revoke the token at Core if present
    if token:
        try:
            core_url = current_app.config['CORE_SERVICE_URL']
            revoke_response = requests.post(
                f"{core_url}/api/token/revoke",
                json={'token': token},
                timeout=5
            )
            if revoke_response.status_code == 200:
                print("Token revoked successfully at Core")
            else:
                print(f"Token revocation failed: {revoke_response.status_code}")
        except Exception as e:
            print(f"Error revoking token: {e}")

    # Clear the Nexus session
    session.clear()

    # Return HTML that clears storage and redirects
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Logged Out</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: #f0f0f0;
            }
            .message {
                text-align: center;
                padding: 2rem;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h2>You have been logged out</h2>
            <p>Redirecting to login...</p>
        </div>
        <script>
            // Clear all browser storage
            if (window.sessionStorage) {
                sessionStorage.clear();
            }
            if (window.localStorage) {
                localStorage.clear();
            }

            // Delete all cookies
            document.cookie.split(";").forEach(function(c) {
                document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
            });

            // Force redirect to home with cache busting
            setTimeout(function() {
                window.location.replace('/?logout=' + Date.now());
            }, 1000);
        </script>
    </body>
    </html>
    """

    response = make_response(html)

    # Delete session cookie server-side
    response.set_cookie('session', '', expires=0, path='/', max_age=0,
                       samesite='Lax', secure=True, httponly=True)

    # Prevent caching
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'

    return response


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def main_gateway(path):
    """
    This is the single entry point for all user-facing requests.
    It handles authentication, token validation, and proxying to services.
    """
    # Proxy Keycloak paths directly without authentication
    # These are needed for the login flow to work
    if path.startswith('realms/') or path.startswith('resources/'):
        import os
        keycloak_url = os.environ.get('KEYCLOAK_SERVER_URL', 'http://localhost:8080')
        backend_url = f"{keycloak_url}/{path}"

        headers = {key: value for (key, value) in request.headers if key.lower() != 'host'}
        headers['X-Forwarded-For'] = request.remote_addr
        headers['X-Forwarded-Proto'] = 'https' if request.is_secure else 'http'
        headers['X-Forwarded-Host'] = request.host
        headers['X-Forwarded-Port'] = '443'
        headers['X-Forwarded-Prefix'] = '/keycloak'

        try:
            resp = requests.request(
                method=request.method,
                url=backend_url,
                headers=headers,
                data=request.get_data(),
                params=request.args,
                cookies=request.cookies,
                allow_redirects=False
            )

            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            response_headers = [(name, value) for (name, value) in resp.raw.headers.items()
                              if name.lower() not in excluded_headers]

            return Response(resp.content, resp.status_code, response_headers)
        except requests.exceptions.RequestException as e:
            return f"Keycloak proxy error: {e}", 502

    # --- Check if user has a token ---
    if 'token' not in session:
        # No token at all - redirect to Nexus's login (which proxies to Core/Keycloak)
        return redirect(url_for('login_proxy', next=request.full_path))

    # --- Validate the token ---
    token = session['token']
    token_data = validate_token(token)

    if not token_data:
        # Token is expired or invalid - clear session and redirect to login
        print(f"Token validation failed for path: {request.full_path}")
        session.clear()
        return redirect(url_for('login_proxy', next=request.full_path))

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
                # Inject global CSS
                css_link = soup.new_tag('link', rel='stylesheet', href=url_for('static', filename='css/global.css'))
                head.append(css_link)

                # Inject side panel CSS
                panel_css_link = soup.new_tag('link', rel='stylesheet', href=url_for('static', filename='css/side-panel.css'))
                head.append(panel_css_link)

            # Inject side panel
            inject_side_panel(soup, service_name)

            content = str(soup)

        return Response(content, resp.status_code, headers)

    except requests.exceptions.RequestException as e:
        return f"Proxy error: {e}", 502
