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


@app.route('/auth-callback')
def auth_callback():
    """
    Callback route for after Core authenticates a user.
    It receives the HiveMatrix JWT, validates it, and sets the local session.
    This route MUST remain public.
    """
    token = request.args.get('token')
    if not token:
        # No token provided, redirect to login
        session.clear()
        core_url = current_app.config['CORE_SERVICE_URL']
        next_url = session.pop('next_url', '/')
        return redirect(f"{core_url}/login?next={request.host_url}auth-callback")

    data = validate_token(token)
    if not data:
        # Invalid or expired token, clear session and redirect to login
        session.clear()
        core_url = current_app.config['CORE_SERVICE_URL']
        next_url = session.pop('next_url', '/')
        return redirect(f"{core_url}/login?next={request.host_url}auth-callback")

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
        print(f"Token validation failed for path: {request.full_path}")
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
