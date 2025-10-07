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
            issuer="hivematrix-core",
            options={"verify_exp": True}
        )
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


@app.route('/login')
def login_proxy():
    """
    Initiates Keycloak login by calling Core's /login endpoint internally,
    then redirecting the user's browser to Keycloak. The callback comes back to Nexus.
    """
    import os

    # Save where the user wanted to go
    session['next_url'] = request.args.get('next', '/')

    # Build the Keycloak authorization URL through Core
    # Core's /login endpoint will generate the Keycloak URL, but we intercept it
    core_url = current_app.config['CORE_SERVICE_URL']
    nexus_auth_callback = url_for('keycloak_callback', _external=True)

    # Call Core's login endpoint with our callback URL
    try:
        # Make internal request to Core to get the Keycloak redirect URL
        resp = requests.get(
            f"{core_url}/login",
            params={'next': nexus_auth_callback},
            allow_redirects=False
        )

        if resp.status_code in [301, 302, 303, 307, 308]:
            # Core redirected to Keycloak - follow that redirect
            keycloak_url = resp.headers.get('Location')
            return redirect(keycloak_url)
        else:
            return f"Unexpected response from Core login: {resp.status_code}", 502

    except requests.exceptions.RequestException as e:
        return f"Login proxy error: {e}", 502


@app.route('/keycloak-callback')
def keycloak_callback():
    """
    Keycloak redirects here after authentication.
    Forward to Core's /auth endpoint to exchange for JWT, then validate and create session.
    """
    core_url = current_app.config['CORE_SERVICE_URL']

    # Forward the callback to Core's /auth endpoint with all query parameters
    core_auth_url = f"{core_url}/auth"
    if request.query_string:
        core_auth_url += f"?{request.query_string.decode()}"

    try:
        # Make request to Core with the same cookies to maintain session
        resp = requests.get(
            core_auth_url,
            allow_redirects=False
        )

        # Core will redirect to next_url with ?token=JWT
        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get('Location', '')

            # Extract token from the redirect URL
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(redirect_url)
            token = parse_qs(parsed.query).get('token', [None])[0]

            if token:
                # Validate and store the token
                token_data = validate_token(token)
                if token_data:
                    session['token'] = token
                    session['user'] = token_data
                    # Redirect to original destination
                    return redirect(session.pop('next_url', '/'))

            # If no token or invalid, redirect to the URL Core provided
            return redirect(redirect_url)

        return f"Unexpected response from Core auth: {resp.status_code}", 502

    except requests.exceptions.RequestException as e:
        return f"Keycloak callback proxy error: {e}", 502




@app.route('/logout')
def logout():
    """
    Clears all sessions: Nexus, Core, and Keycloak.
    Returns HTML that calls Core logout, then Keycloak logout, then redirects to Nexus.
    """
    from flask import make_response
    import os

    # Clear Nexus session
    session.clear()

    # Get configuration
    core_url = current_app.config['CORE_SERVICE_URL']
    keycloak_url = os.environ.get('KEYCLOAK_SERVER_URL', 'http://localhost:8080')
    keycloak_realm = os.environ.get('KEYCLOAK_REALM', 'hivematrix')
    nexus_url = current_app.config.get('NEXUS_SERVICE_URL', 'http://localhost:8000')

    # Return HTML that performs multi-step logout
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Logging out...</title>
        <meta http-equiv="refresh" content="2;url={keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/logout?redirect_uri={nexus_url}">
    </head>
    <body>
        <p>Logging out...</p>
        <iframe src="{core_url}/logout" style="display:none;" onload="console.log('Core logout called')"></iframe>
        <script>
            // After 1.5 seconds, redirect to Keycloak logout
            setTimeout(function() {{
                window.location.href = '{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/logout?redirect_uri={nexus_url}';
            }}, 1500);
        </script>
    </body>
    </html>
    """

    response = make_response(html)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'

    # Delete Nexus session cookie
    response.delete_cookie('session', path='/')

    return response


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def main_gateway(path):
    """
    This is the single entry point for all user-facing requests.
    It handles authentication, token validation, and proxying to services.
    """
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
