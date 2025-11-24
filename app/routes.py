import os
import re
import requests
import secrets
import time
import sys
from urllib.parse import urlencode

from flask import request, Response, url_for, session, redirect, current_app, make_response
from app import app, limiter
from app.service_client import call_service
from bs4 import BeautifulSoup
import jwt

# Health check library
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from health_check import HealthChecker

# Cache TTL for user preferences (5 minutes)
PREFERENCE_CACHE_TTL = 300

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
                current_app.logger.warning(f"Token validation failed at Core: {validation_response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            # If Core is unreachable, fall back to local validation
            # This ensures the system keeps working even if Core is down
            current_app.logger.warning(f"Could not reach Core for validation: {e}, falling back to local validation")
            return data

    except jwt.ExpiredSignatureError:
        return None
    except jwt.PyJWTError as e:
        current_app.logger.warning(f"Token validation failed: {e}")
        return None


def get_user_theme(token_data):
    """
    Fetch user's theme preferences from Codex with session caching.
    Falls back to defaults if Codex is unavailable or user not found.

    Args:
        token_data: Decoded JWT token containing user info

    Returns:
        dict: {'theme': 'light'|'dark', 'color_theme': 'purple'|'blue'|'green'|'orange'|'gold'}
    """
    user_email = token_data.get('email')
    current_app.logger.debug(f"get_user_theme called for email: {user_email}")

    default_prefs = {'theme': 'light', 'color_theme': 'purple'}

    if not user_email:
        current_app.logger.debug("No email in token, defaulting to light theme")
        return default_prefs

    # Check session cache first
    cached_theme = session.get('cached_theme')
    cached_color_theme = session.get('cached_color_theme')
    cache_time = session.get('cached_theme_time', 0)

    if cached_theme and cached_color_theme and (time.time() - cache_time) < PREFERENCE_CACHE_TTL:
        current_app.logger.debug(f"Using cached themes: {cached_theme}, {cached_color_theme}")
        return {'theme': cached_theme, 'color_theme': cached_color_theme}

    try:
        # Call Codex API using proper service-to-service authentication
        response = call_service(
            'codex',
            '/api/public/user/theme',
            params={'email': user_email},
            timeout=2  # Quick timeout to avoid slowing down page loads
        )

        current_app.logger.debug(f"Codex theme API response: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            theme = data.get('theme', 'light')
            color_theme = data.get('color_theme', 'purple')
            current_app.logger.debug(f"Themes from Codex: {theme}, {color_theme}")

            # Validate theme values
            if theme in ['light', 'dark'] and color_theme in ['purple', 'blue', 'green', 'orange', 'gold', 'red', 'yellow', 'matrix', 'bee']:
                # Cache in session
                session['cached_theme'] = theme
                session['cached_color_theme'] = color_theme
                session['cached_theme_time'] = time.time()
                return {'theme': theme, 'color_theme': color_theme}

    except Exception as e:
        # Log error but don't fail the page load
        current_app.logger.warning(f"Failed to fetch user theme from Codex: {e}")

    # Default to light theme if anything goes wrong
    current_app.logger.debug("Defaulting to default themes")
    return default_prefs


def get_user_home_page(token_data):
    """
    Fetch user's home page preference from Codex with session caching.
    Falls back to 'helm' if Codex is unavailable or user not found.

    Args:
        token_data: Decoded JWT token containing user info

    Returns:
        str: Service slug (e.g., 'helm', 'codex', 'beacon', 'ledger', 'brainhair')
    """
    user_email = token_data.get('email')
    current_app.logger.debug(f"get_user_home_page called for email: {user_email}")

    if not user_email:
        current_app.logger.debug("No email in token, defaulting to helm")
        return 'helm'  # Default if no email in token

    # Check session cache first
    cached_home = session.get('cached_home_page')
    cache_time = session.get('cached_home_page_time', 0)

    if cached_home and (time.time() - cache_time) < PREFERENCE_CACHE_TTL:
        current_app.logger.debug(f"Using cached home page: {cached_home}")
        return cached_home

    try:
        # Call Codex API using proper service-to-service authentication
        response = call_service(
            'codex',
            '/api/public/user/home-page',
            params={'email': user_email},
            timeout=2  # Quick timeout to avoid slowing down redirects
        )

        current_app.logger.debug(f"Codex home page API response: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            home_page = data.get('home_page', 'helm')
            current_app.logger.debug(f"Home page from Codex: {home_page}")

            # Validate home page value
            valid_pages = ['helm', 'codex', 'beacon', 'ledger', 'brainhair']
            if home_page in valid_pages:
                # Cache in session
                session['cached_home_page'] = home_page
                session['cached_home_page_time'] = time.time()
                return home_page

    except Exception as e:
        # Log error but don't fail the redirect
        current_app.logger.warning(f"Failed to fetch user home page from Codex: {e}")

    # Default to helm if anything goes wrong
    current_app.logger.debug("Defaulting to helm")
    return 'helm'


def invalidate_preference_cache():
    """
    Clear cached user preferences. Call this when user updates their settings.
    """
    session.pop('cached_theme', None)
    session.pop('cached_color_theme', None)
    session.pop('cached_theme_time', None)
    session.pop('cached_home_page', None)
    session.pop('cached_home_page_time', None)


@app.route('/api/invalidate-cache', methods=['POST'])
def invalidate_cache_endpoint():
    """
    Endpoint to invalidate user preference cache.
    Called by the theme toggle after saving to Codex.
    """
    invalidate_preference_cache()
    return jsonify({'success': True, 'message': 'Cache invalidated'})


def inject_side_panel(soup, current_service, user_data=None):
    """Injects the side panel navigation into the HTML."""
    services = current_app.config.get('SERVICES', {})
    user_permission = user_data.get('permission_level', 'client') if user_data else 'client'

    # Create side panel HTML
    side_panel_html = '''
    <div class="hivematrix-side-panel" id="side-panel">
        <div class="side-panel__header">
            <button class="side-panel__toggle" id="sidebar-toggle" aria-label="Toggle sidebar">
                <svg viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            </button>
            <h3 class="side-panel__title">HiveMatrix</h3>
        </div>
        <nav class="side-panel__nav">
            <ul class="side-panel__list">
    '''

    # Service icons mapping - Lucide icons to match Helm dashboard
    service_icons = {
        'template': '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>',
        'codex': '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
        'knowledgetree': '<svg viewBox="0 0 24 24"><path d="M10 10v.2A3 3 0 0 1 8.9 16v0H5v0h0a3 3 0 0 1-1-5.8V10a3 3 0 0 1 6 0Z"/><path d="M7 16v6"/><path d="M13 19v3"/><path d="M12 19h8.3a1 1 0 0 0 .7-1.7L18 14h.3a1 1 0 0 0 .7-1.7L16 9h.2a1 1 0 0 0 .8-1.7L13 3l-1.1 1.7"/></svg>',
        'ledger': '<svg viewBox="0 0 24 24"><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1-2-1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17V7"/></svg>',
        'resolve': '<svg viewBox="0 0 24 24"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
        'architect': '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>',
        'treasury': '<svg viewBox="0 0 24 24"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>',
        'core': '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
        'nexus': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><path d="M10.4 21.9a10 10 0 0 0 9.941-15.416"/><path d="M13.5 2.1a10 10 0 0 0-9.841 15.416"/></svg>',
        'helm': '<svg viewBox="0 0 24 24"><path d="M12 6v16"/><path d="m19 13 2-1a9 9 0 0 1-18 0l2 1"/><path d="M9 11h6"/><circle cx="12" cy="4" r="2"/></svg>',
        'brainhair': '<svg viewBox="0 0 24 24"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M19.967 17.484A4 4 0 0 1 18 18"/></svg>',
        'beacon': '<svg viewBox="0 0 24 24"><path d="M4.9 16.1C1 12.2 1 5.8 4.9 1.9"/><path d="M7.8 4.7a6.14 6.14 0 0 0-.8 7.5"/><circle cx="12" cy="9" r="2"/><path d="M16.2 4.8c2 2 2.26 5.11.8 7.47"/><path d="M19.1 1.9a9.96 9.96 0 0 1 0 14.1"/><path d="M9.5 18h5"/><path d="m8 22 4-11 4 11"/></svg>',
        'archive': '<svg viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/><path d="m7.9 7.9 2.7 2.7"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/><path d="m13.4 10.6 2.7-2.7"/><circle cx="7.5" cy="16.5" r=".5" fill="currentColor"/><path d="m7.9 16.1 2.7-2.7"/><circle cx="16.5" cy="16.5" r=".5" fill="currentColor"/><path d="m13.4 13.4 2.7 2.7"/><circle cx="12" cy="12" r="2"/></svg>'
    }

    # Add each service as a link (only if visible and user has permission)
    for service_name, service_config in services.items():
        # Skip services that are not visible
        if not service_config.get('visible', True):
            continue

        # Skip admin-only services if user is not admin
        if service_config.get('admin_only', False) and user_permission != 'admin':
            continue

        # Skip billing/admin-only services if user is not admin or billing
        if service_config.get('billing_or_admin_only', False) and user_permission not in ['admin', 'billing']:
            continue

        icon = service_icons.get(service_name, '📦')
        active_class = 'side-panel__item--active' if service_name == current_service else ''
        display_name = service_name.title()

        tooltip_text = f"Go to {display_name}"
        side_panel_html += f'''
            <li class="side-panel__item {active_class}">
                <a href="/{service_name}/" class="side-panel__link" data-tooltip="{tooltip_text}" data-tooltip-position="right">
                    <span class="side-panel__icon">{icon}</span>
                    <span class="side-panel__label">{display_name}</span>
                </a>
            </li>
        '''

    side_panel_html += '''
            </ul>
        </nav>
        <div class="side-panel__footer">
            <a href="/codex/settings" class="side-panel__link" data-tooltip="Change theme and preferences" data-tooltip-position="right">
                <span class="side-panel__icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></span>
                <span class="side-panel__label">Settings</span>
            </a>
            <a href="/logout" class="side-panel__link" data-tooltip="Sign out of HiveMatrix" data-tooltip-position="right">
                <span class="side-panel__icon"><svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg></span>
                <span class="side-panel__label">Logout</span>
            </a>
            <button class="theme-toggle" id="theme-toggle-btn" aria-label="Toggle theme" data-tooltip="Toggle light/dark mode" data-tooltip-position="right">
                <span class="theme-toggle__track">
                    <span class="theme-toggle__thumb">
                        <svg viewBox="0 0 24 24" class="theme-icon-moon"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
                        <svg viewBox="0 0 24 24" class="theme-icon-sun"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                    </span>
                </span>
            </button>
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

        # Inject theme toggle script at end of body (separate from HTML to avoid BeautifulSoup mangling)
        theme_script = soup.new_tag('script')
        theme_script.string = '''
console.log('[Theme Toggle] Script loaded');

// Theme toggle functionality
function getCurrentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
}

async function toggleTheme() {
    console.log('[Theme Toggle] toggleTheme() called');
    const currentTheme = getCurrentTheme();
    console.log('[Theme Toggle] Current theme:', currentTheme);
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    console.log('[Theme Toggle] New theme:', newTheme);

    // Apply theme immediately
    document.documentElement.setAttribute('data-theme', newTheme);
    console.log('[Theme Toggle] data-theme attribute set to:', newTheme);

    // Save to Codex with proper authentication
    try {
        console.log('[Theme Toggle] Sending request to /codex/api/my/settings');
        const response = await fetch('/codex/api/my/settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({ theme_preference: newTheme })
        });

        console.log('[Theme Toggle] Response status:', response.status);

        if (!response.ok) {
            // Try to parse error response
            let errorMessage = 'Unknown error';
            let isAgentNotSynced = false;

            try {
                const result = await response.json();
                errorMessage = result.error || errorMessage;
                isAgentNotSynced = result.error && result.error.includes('Agent not found');
            } catch (parseError) {
                // Response wasn't JSON - likely an authentication error
                console.error('Non-JSON error response:', parseError);
                errorMessage = 'Authentication failed - please refresh the page and try again';
            }

            console.error('Failed to save theme preference:', response.status, errorMessage);

            if (response.status === 404 && isAgentNotSynced) {
                alert('Theme changed locally but not saved:\\n\\nYour account needs to be synced from Keycloak.\\nAsk an admin to sync agents in Codex Settings.');
            } else if (response.status === 401 || response.status === 403) {
                alert('Theme changed locally but not saved:\\n\\nAuthentication error. Please refresh the page and try again.');
            } else {
                console.error('Theme save error:', response.status, errorMessage);
                // Show a less intrusive message for other errors
                console.warn('Theme applied locally but may not persist across sessions');
            }
        } else {
            const result = await response.json();
            console.log('Theme saved successfully:', newTheme);

            // Invalidate Nexus cache so next page load uses new theme
            try {
                await fetch('/api/invalidate-cache', {
                    method: 'POST',
                    credentials: 'same-origin'
                });
                console.log('Nexus cache invalidated');
            } catch (cacheError) {
                console.warn('Failed to invalidate cache:', cacheError);
            }
        }
    } catch (error) {
        console.error('Error saving theme:', error);
        alert('Theme changed locally but not saved:\\n\\nNetwork error: ' + error.message + '\\n\\nPlease check your connection and try again.');
    }
}

// Sidebar toggle functionality
function toggleSidebar() {
    const sidePanel = document.getElementById('side-panel');
    if (sidePanel) {
        sidePanel.classList.toggle('collapsed');
        const isCollapsed = sidePanel.classList.contains('collapsed');
        localStorage.setItem('sidebar-collapsed', isCollapsed);
        console.log('[Sidebar] Toggled, collapsed:', isCollapsed);
    }
}

function initSidebar() {
    const sidePanel = document.getElementById('side-panel');
    const savedState = localStorage.getItem('sidebar-collapsed');

    if (savedState === 'true' && sidePanel) {
        // Add collapsed class to sidebar for future toggles
        sidePanel.classList.add('collapsed');
    }

    // Remove the initial no-transition class and re-enable transitions
    // Use requestAnimationFrame to ensure styles are applied first
    requestAnimationFrame(() => {
        document.documentElement.classList.remove('sidebar-collapsed');
    });
}

// Attach event listeners on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Theme Toggle] DOMContentLoaded fired');

    // Initialize sidebar state from localStorage
    initSidebar();

    // Attach click handler to theme toggle
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        console.log('[Theme Toggle] Toggle found, attaching listener');
        themeBtn.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('[Theme Toggle] Toggle clicked');
            toggleTheme();
        });
    } else {
        console.error('[Theme Toggle] Toggle not found!');
    }

    // Attach click handler to sidebar toggle
    const sidebarBtn = document.getElementById('sidebar-toggle');
    if (sidebarBtn) {
        console.log('[Sidebar] Toggle found, attaching listener');
        sidebarBtn.addEventListener('click', function(e) {
            e.preventDefault();
            toggleSidebar();
        });
    }
});
'''
        body.append(theme_script)

@app.route('/health')
@limiter.exempt
def health():
    """
    Comprehensive health check endpoint.

    Checks:
    - Disk space
    - Core service availability
    - Keycloak availability

    Returns:
        JSON: Detailed health status with HTTP 200 (healthy) or 503 (unhealthy/degraded)
    """
    # Initialize health checker with dependencies
    health_checker = HealthChecker(
        service_name='nexus',
        dependencies=[
            ('core', 'http://localhost:5000'),
            ('keycloak', current_app.config.get('KEYCLOAK_SERVER_URL', 'http://localhost:8080'))
        ]
    )

    return health_checker.get_health()


@app.route('/helpdesk')
@app.route('/helpdesk/')
def helpdesk_redirect():
    """Redirect /helpdesk to Beacon's helpdesk view."""
    return redirect('/beacon/helpdesk')


@app.route('/professional-services')
@app.route('/professional-services/')
def professional_services_redirect():
    """Redirect /professional-services to Beacon's professional services view."""
    return redirect('/beacon/professional-services')


@app.route('/keycloak/', defaults={'path': ''})
@app.route('/keycloak/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def keycloak_proxy(path):
    """
    Proxy requests to Keycloak server.
    This allows external browsers to access Keycloak through Nexus's HTTPS endpoint.
    """
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
            allow_redirects=False,
            timeout=30
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
            except (UnicodeDecodeError, UnicodeEncodeError) as e:
                current_app.logger.debug(f"Could not rewrite Keycloak response content: {e}")

        return Response(content, resp.status_code, response_headers)

    except requests.exceptions.RequestException as e:
        return f"Keycloak proxy error: {e}", 502


@app.route('/login')
def login_proxy():
    """
    Initiates Keycloak login by building the authorization URL directly.
    This ensures external-facing URLs are used instead of localhost.
    """
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
            if revoke_response.status_code != 200:
                current_app.logger.warning(f"Token revocation failed: {revoke_response.status_code}")
        except Exception as e:
            current_app.logger.warning(f"Error revoking token: {e}")

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
                allow_redirects=False,
                timeout=30
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
        session.clear()
        return redirect(url_for('login_proxy', next=request.full_path))

    # Update session with fresh token data (in case it was decoded again)
    session['user'] = token_data

    # If the path is empty, redirect to the user's preferred home page
    if not path:
        services = current_app.config.get('SERVICES', {})
        user_permission = token_data.get('permission_level', 'client')

        # Get user's preferred home page from Codex
        preferred_home = get_user_home_page(token_data)

        # Check if user has access to their preferred home page
        if preferred_home in services:
            service_config = services[preferred_home]
            # Check if user has permission
            if service_config.get('admin_only', False) and user_permission != 'admin':
                preferred_home = None  # Fall back to first accessible
            elif service_config.get('billing_or_admin_only', False) and user_permission not in ['admin', 'billing']:
                preferred_home = None  # Fall back to first accessible
            elif not service_config.get('visible', True):
                preferred_home = None  # Fall back to first accessible
        else:
            preferred_home = None  # Invalid service, fall back

        # If preferred home is valid and accessible, use it
        if preferred_home:
            return redirect(f'/{preferred_home}/')

        # Fall back to first accessible service
        first_accessible = None
        for service_name, service_config in services.items():
            # Skip if not visible
            if not service_config.get('visible', True):
                continue
            # Skip if admin_only and user is not admin
            if service_config.get('admin_only', False) and user_permission != 'admin':
                continue
            first_accessible = service_name
            break

        if first_accessible:
            return redirect(f'/{first_accessible}/')
        else:
            return "<h1>HiveMatrix Nexus</h1><p>No services available for your permission level.</p>", 200

    # Determine service from the first part of the path
    path_parts = path.split('/')
    service_name = path_parts[0]
    service_path = '/'.join(path_parts[1:])

    services = current_app.config.get('SERVICES', {})
    service_config = services.get(service_name)

    if not service_config:
        return f"Service '{service_name}' not found.", 404

    backend_url = f"{service_config['url']}/{service_path}"

    # --- Add Auth Header and X-Forwarded Headers to Proxied Request ---
    headers = {key: value for (key, value) in request.headers if key != 'Host'}
    headers['Authorization'] = f"Bearer {token}"

    # Add X-Forwarded headers so backend knows it's behind a proxy
    headers['X-Forwarded-For'] = request.remote_addr
    headers['X-Forwarded-Proto'] = 'https' if request.is_secure else 'http'
    headers['X-Forwarded-Host'] = request.host
    headers['X-Forwarded-Prefix'] = f'/{service_name}'

    try:
        # Always enable streaming so we can detect SSE responses
        resp = requests.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            params=request.args,  # Forward query string parameters
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,  # Always stream so we can check content-type
            timeout=30)  # Prevent hanging requests

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for (name, value) in resp.raw.headers.items() if name.lower() not in excluded_headers]

        # If streaming response (SSE), stream it back immediately without buffering
        if 'text/event-stream' in resp.headers.get('Content-Type', ''):
            def generate():
                for chunk in resp.iter_content(chunk_size=1024, decode_unicode=False):
                    if chunk:
                        yield chunk
            return Response(generate(), resp.status_code, response_headers)

        # Otherwise, read all content for HTML injection or normal responses
        # When using stream=True, we must consume the entire response
        content = b''.join(resp.iter_content(chunk_size=8192))

        if 'text/html' in resp.headers.get('Content-Type', ''):
            soup = BeautifulSoup(content, 'html.parser')

            # Add data-theme and data-color-theme attributes to html tag
            # Fetch user's theme preferences from Codex
            html_tag = soup.find('html')
            if html_tag:
                theme_prefs = get_user_theme(token_data)
                html_tag['data-theme'] = theme_prefs['theme']
                html_tag['data-color-theme'] = theme_prefs['color_theme']

            head = soup.find('head')
            if head:
                # Inject global CSS with cache-busting
                from app.version import VERSION
                css_link = soup.new_tag('link', rel='stylesheet', href=f"{url_for('static', filename='css/global.css')}?v={VERSION}")
                head.append(css_link)

                # Inject side panel CSS with cache-busting
                panel_css_link = soup.new_tag('link', rel='stylesheet', href=f"{url_for('static', filename='css/side-panel.css')}?v={VERSION}")
                head.append(panel_css_link)

                # Inject inline script to prevent sidebar flash on page load
                # This runs immediately before render to set collapsed state
                sidebar_init_script = soup.new_tag('script')
                sidebar_init_script.string = '''
                    (function() {
                        if (localStorage.getItem('sidebar-collapsed') === 'true') {
                            document.documentElement.classList.add('sidebar-collapsed');
                        }
                    })();
                '''
                head.append(sidebar_init_script)

                # Inject Matrix rain Easter egg animation
                matrix_rain_script = soup.new_tag('script')
                matrix_rain_script.string = '''
                    document.addEventListener('DOMContentLoaded', function() {
                        // Create canvas for Matrix rain
                        const canvas = document.createElement('canvas');
                        canvas.id = 'matrix-rain';
                        document.body.insertBefore(canvas, document.body.firstChild);

                        const ctx = canvas.getContext('2d');

                        // Matrix characters - Katakana + Latin + numbers
                        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%^&*()ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ';
                        const fontSize = 14;
                        let columns = 0;
                        let drops = [];

                        // Set canvas size and recalculate columns/drops
                        function resizeCanvas() {
                            canvas.width = window.innerWidth;
                            canvas.height = window.innerHeight;

                            // Recalculate columns for new width
                            const newColumns = Math.floor(canvas.width / fontSize);

                            // Only reset drops if column count changed
                            if (newColumns !== columns) {
                                columns = newColumns;
                                drops = Array(columns).fill(1).map(() => Math.floor(Math.random() * canvas.height / fontSize));
                            }
                        }
                        resizeCanvas();
                        window.addEventListener('resize', resizeCanvas);

                        // Frame counter for slower animation
                        let frameCount = 0;
                        const frameSkip = 2; // Draw every 3rd frame (slower animation)

                        function drawMatrixRain() {
                            // Check if Matrix theme is active
                            const isMatrixTheme = document.documentElement.getAttribute('data-color-theme') === 'matrix';
                            if (!isMatrixTheme) {
                                ctx.clearRect(0, 0, canvas.width, canvas.height);
                                requestAnimationFrame(drawMatrixRain);
                                return;
                            }

                            // Only update every frameSkip frames for slower animation
                            frameCount++;
                            if (frameCount % (frameSkip + 1) !== 0) {
                                requestAnimationFrame(drawMatrixRain);
                                return;
                            }

                            // Semi-transparent black to create fade effect
                            ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
                            ctx.fillRect(0, 0, canvas.width, canvas.height);

                            // Matrix green text
                            ctx.fillStyle = '#00ff41';
                            ctx.font = fontSize + 'px monospace';

                            for (let i = 0; i < drops.length; i++) {
                                const char = chars[Math.floor(Math.random() * chars.length)];
                                const x = i * fontSize;
                                const y = drops[i] * fontSize;

                                ctx.fillText(char, x, y);

                                // Reset drop to top randomly after it falls off screen
                                if (y > canvas.height && Math.random() > 0.975) {
                                    drops[i] = 0;
                                }

                                drops[i]++;
                            }

                            requestAnimationFrame(drawMatrixRain);
                        }

                        // Start animation
                        drawMatrixRain();
                    });
                '''
                head.append(matrix_rain_script)

                # Inject Bee Easter egg animation
                bee_flight_script = soup.new_tag('script')
                bee_flight_script.string = '''
                    document.addEventListener('DOMContentLoaded', function() {
                        // Create bee container
                        const beeContainer = document.createElement('div');
                        beeContainer.id = 'bee-container';
                        document.body.insertBefore(beeContainer, document.body.firstChild);

                        let activeBees = 0;
                        const maxBees = 5;
                        const beeEmoji = '🐝';

                        function createBee() {
                            // Check if bee theme is active
                            const isBeeTheme = document.documentElement.getAttribute('data-color-theme') === 'bee';
                            if (!isBeeTheme || activeBees >= maxBees) {
                                return;
                            }

                            activeBees++;
                            const bee = document.createElement('div');
                            bee.className = 'bee';
                            bee.textContent = beeEmoji;

                            // Random size (20px to 32px)
                            const size = 20 + Math.random() * 12;
                            bee.style.fontSize = size + 'px';

                            // Random starting position (top third of screen)
                            const startY = Math.random() * (window.innerHeight / 3);
                            const startX = Math.random() < 0.5 ? -50 : window.innerWidth + 50;
                            const endX = startX < 0 ? window.innerWidth + 50 : -50;

                            // Determine direction: flip bee based on flight direction
                            const flyingLeftToRight = startX < 0;
                            if (flyingLeftToRight) {
                                bee.style.transform = 'scaleX(-1)';
                            }

                            // Random end position (different height)
                            const endY = startY + (Math.random() - 0.5) * 200;

                            // Random duration (3-6 seconds)
                            const duration = 3000 + Math.random() * 3000;

                            bee.style.left = startX + 'px';
                            bee.style.top = startY + 'px';

                            beeContainer.appendChild(bee);

                            // Animate bee
                            let startTime = Date.now();

                            function animateBee() {
                                const elapsed = Date.now() - startTime;
                                const progress = Math.min(elapsed / duration, 1);

                                if (progress >= 1) {
                                    bee.remove();
                                    activeBees--;
                                    return;
                                }

                                // Ease in-out progress
                                const easeProgress = progress < 0.5
                                    ? 2 * progress * progress
                                    : 1 - Math.pow(-2 * progress + 2, 2) / 2;

                                // Calculate position with sine wave for curved path
                                const currentX = startX + (endX - startX) * easeProgress;
                                const currentY = startY + (endY - startY) * easeProgress +
                                                Math.sin(easeProgress * Math.PI * 2) * 30;

                                // Fade in/out at edges
                                let opacity = 1;
                                if (progress < 0.1) {
                                    opacity = progress / 0.1;
                                } else if (progress > 0.9) {
                                    opacity = (1 - progress) / 0.1;
                                }

                                bee.style.left = currentX + 'px';
                                bee.style.top = currentY + 'px';
                                bee.style.opacity = opacity;

                                requestAnimationFrame(animateBee);
                            }

                            requestAnimationFrame(animateBee);
                        }

                        // Spawn bees at random intervals (3-6 seconds)
                        function scheduleBee() {
                            const delay = 3000 + Math.random() * 3000;
                            setTimeout(() => {
                                createBee();
                                scheduleBee();
                            }, delay);
                        }

                        // Start with a small delay
                        setTimeout(() => {
                            createBee();
                            scheduleBee();
                        }, 1000);
                    });
                '''
                head.append(bee_flight_script)

            # Inject side panel with user data
            inject_side_panel(soup, service_name, token_data)

            content = str(soup)

        return Response(content, resp.status_code, response_headers)

    except requests.exceptions.RequestException as e:
        return f"Proxy error: {e}", 502
