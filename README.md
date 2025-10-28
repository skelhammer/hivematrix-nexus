# HiveMatrix Nexus

**HTTPS Gateway & UI Composition Layer**

Nexus is the user-facing gateway for the entire HiveMatrix platform. It provides a unified HTTPS entry point, handles OAuth2 authentication via Keycloak, and composes UIs from multiple backend services.

---

## Quick Start

**For first-time setup of the entire HiveMatrix ecosystem:**

👉 **Start with [hivematrix-helm](../hivematrix-helm/README.md)** 👈

Helm is the orchestration center that will guide you through setting up Keycloak, Core, Nexus, and all other services using the automated `start.sh` script.

**IMPORTANT:** Read [ARCHITECTURE.md](../hivematrix-helm/ARCHITECTURE.md) before making any code changes.

---

## What Nexus Does

- **HTTPS Gateway**: Runs on port 443 with SSL/TLS for secure external access
- **Smart Reverse Proxy**: Routes requests to backend services based on URL paths
- **OAuth2 Authentication**: Integrates with Keycloak for user authentication
- **Session Management**: Maintains revokable user sessions with JWT tokens
- **UI Composition**: Injects global CSS, side panel navigation, and theme preferences
- **Keycloak Proxy**: Proxies `/keycloak/` requests to allow external Keycloak access
- **Service Discovery**: Automatically discovers backend services via `services.json`
- **Theme Management**: Fetches and applies user theme preferences (light/dark mode)

---

## Architecture

See [ARCHITECTURE.md](../hivematrix-helm/ARCHITECTURE.md) for complete system architecture and development guidelines.

### Request Flow

```
1. User accesses https://your-server:443/codex/
2. Nexus checks for valid session token
3. If no session:
   a. Redirects to /login
   b. Proxies to Keycloak OAuth2 authorization endpoint (/keycloak/realms/...)
   c. User enters credentials on Keycloak login page
   d. Keycloak redirects to /keycloak-callback with authorization code
   e. Nexus exchanges code for Keycloak access token
   f. Nexus sends access token to Core's /api/token/exchange
   g. Core validates with Keycloak, creates session, mints HiveMatrix JWT
   h. Nexus stores JWT in Flask session
4. Nexus validates JWT with Core (checks signature and revocation status)
5. Nexus fetches user's theme preference from Codex
6. Nexus proxies request to Codex at http://localhost:5010/
7. Adds Authorization: Bearer <JWT> header
8. Adds X-Forwarded-* headers (Prefix, Proto, Host, For)
9. Receives HTML response from backend service
10. Injects global CSS and side panel navigation
11. Applies user's theme preference (data-theme attribute)
12. Returns composed UI to user
```

---

## Prerequisites

- **Python 3.8+**
- **HiveMatrix Core** running on port 5000
- **Keycloak** running on port 8080
- **Backend services** (Codex, Ledger, etc.) running on their ports
- **SSL certificates** for port 443 (self-signed for dev, valid for production)

---

## Installation

### Automated (Recommended)

Use Helm's `start.sh` script which handles all installation and configuration:

```bash
cd /path/to/hivematrix-helm
./start.sh
```

This will:
1. Install Nexus if not present
2. Generate SSL certificates
3. Configure environment variables
4. Start Nexus on port 443 with HTTPS

### Manual Installation

#### 1. Clone and Setup

```bash
git clone https://github.com/Troy Pound/hivematrix-nexus
cd hivematrix-nexus
python3 -m venv pyenv
source pyenv/bin/activate
pip install -r requirements.txt
```

#### 2. Generate SSL Certificates

For development (self-signed):

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout certs/nexus.key \
  -out certs/nexus.crt \
  -days 365 \
  -subj "/CN=localhost"
```

For production: Use Let's Encrypt or a commercial SSL certificate.

#### 3. Configure Environment

The `.flaskenv` file is **auto-generated** by Helm's `config_manager.py`. Do not edit manually.

If manually installing (outside Helm), create `.flaskenv`:

```bash
FLASK_APP=run.py
FLASK_ENV=production
SECRET_KEY=<generate-random-secret-key>
SERVICE_NAME=nexus

# Keycloak Configuration
KEYCLOAK_SERVER_URL=http://localhost:8080
KEYCLOAK_BACKEND_URL=http://localhost:8080
KEYCLOAK_REALM=hivematrix
KEYCLOAK_CLIENT_ID=core-client
KEYCLOAK_CLIENT_SECRET=<from-keycloak-admin-console>

# Service URLs
CORE_SERVICE_URL=http://localhost:5000
NEXUS_SERVICE_URL=https://your-server:443
HELM_SERVICE_URL=http://localhost:5004

# Nexus Runtime
NEXUS_PORT=443
NEXUS_HOST=0.0.0.0
USE_GUNICORN=true
```

**Security Note:** Generate a strong `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

#### 4. Configure Services

Create `services.json` symlink (or copy from Helm):

```bash
ln -s ../hivematrix-helm/services.json services.json
```

Example `services.json`:
```json
{
  "helm": {
    "url": "http://localhost:5004",
    "visible": true,
    "admin_only": true
  },
  "codex": {
    "url": "http://localhost:5010",
    "visible": true
  },
  "ledger": {
    "url": "http://localhost:5030",
    "visible": true
  }
}
```

Only services with `"visible": true` appear in the sidebar navigation.

#### 5. Run Nexus

**Development (HTTP on port 8000):**
```bash
export NEXUS_PORT=8000
export USE_GUNICORN=false
python run.py
```

**Production (HTTPS on port 443):**
```bash
# Port 443 requires root or CAP_NET_BIND_SERVICE capability
sudo setcap cap_net_bind_service=+ep pyenv/bin/python3

# Run with gunicorn (production)
export NEXUS_PORT=443
export USE_GUNICORN=true
python run.py
```

Nexus will:
- Detect port 443 and automatically use Gunicorn with SSL
- Use gevent workers for SSE (Server-Sent Events) support
- Serve on `https://localhost:443` or `https://your-server:443`

---

## How It Works

### Service Routing

Nexus routes requests based on the first URL segment:

| URL | Backend | Notes |
|-----|---------|-------|
| `/codex/companies` | `http://localhost:5010/companies` | Strips `/codex` prefix |
| `/ledger/invoices` | `http://localhost:5030/invoices` | Adds Authorization header |
| `/helm/status` | `http://localhost:5004/status` | Admin-only by default |
| `/keycloak/realms/...` | `http://localhost:8080/realms/...` | Keycloak proxy (no auth) |

**Important:** Nexus strips the service prefix before forwarding. Backend services receive clean paths without the service name.

### Authentication Flow (OAuth2 via Keycloak)

1. **Login Request:** User visits protected route → Nexus checks session
2. **OAuth Redirect:** No session → redirects to `/login`
3. **Keycloak Authorization:** Nexus redirects to Keycloak login page (via `/keycloak/` proxy)
4. **User Login:** User enters credentials, Keycloak validates
5. **Authorization Code:** Keycloak redirects to `/keycloak-callback?code=...`
6. **Token Exchange:** Nexus exchanges code for Keycloak access token
7. **JWT Minting:** Nexus sends access token to Core → Core validates with Keycloak → Core mints HiveMatrix JWT
8. **Session Creation:** Core creates revokable session, returns JWT
9. **Session Storage:** Nexus stores JWT in Flask session cookie
10. **Redirect:** User redirected to original destination with active session

### Token Validation

On every request, Nexus:
1. Validates JWT signature using Core's public key (JWKS)
2. Checks token hasn't expired (exp claim)
3. Calls Core's `/api/token/validate` to check if session is revoked
4. If any check fails, clears session and redirects to login

### Session Revocation

Sessions can be revoked (e.g., on logout):
1. User clicks logout → Nexus calls Core's `/api/token/revoke`
2. Core marks session as revoked in session store
3. Next request with that token → validation fails → user must re-login

This ensures logout works immediately across all services.

### UI Composition

For HTML responses, Nexus:

1. **Injects Global CSS:**
   ```html
   <link rel="stylesheet" href="/static/css/global.css">
   <link rel="stylesheet" href="/static/css/side-panel.css">
   ```

2. **Applies Theme:** Fetches user's theme preference from Codex and sets:
   ```html
   <html data-theme="dark">
   ```

3. **Injects Side Panel:** Adds navigation panel with:
   - Service links (filtered by user permissions)
   - Theme toggle button (light/dark mode)
   - Settings link
   - Logout link

4. **Wraps Content:**
   ```html
   <div class="hivematrix-layout">
     <div class="hivematrix-side-panel">...</div>
     <div class="hivematrix-content">
       <!-- Original service content -->
     </div>
   </div>
   ```

### Theme Management

Nexus fetches user theme preferences from Codex:

```python
GET /codex/api/public/user/theme?email=user@example.com
Response: {"theme": "dark", "source": "codex"}
```

- Default: `light` if user not found or Codex unavailable
- Theme is applied via `data-theme` attribute on `<html>` tag
- CSS variables in `global.css` respond to `[data-theme="dark"]`

### Keycloak Proxy

Nexus proxies Keycloak at `/keycloak/` to allow external access:

- **Why:** Keycloak runs on localhost:8080 (not externally accessible)
- **How:** Nexus rewrites URLs, cookies, and HTML to proxy through HTTPS
- **Example:** `https://your-server/keycloak/realms/hivematrix` → `http://localhost:8080/realms/hivematrix`

This allows external browsers to access Keycloak login pages securely through Nexus's HTTPS endpoint.

### X-Forwarded Headers

Nexus adds headers for backend services using ProxyFix:

```python
X-Forwarded-For: <client-ip>
X-Forwarded-Proto: https
X-Forwarded-Host: your-server:443
X-Forwarded-Prefix: /codex
```

Backend services use `werkzeug.middleware.proxy_fix.ProxyFix` to respect these headers for URL generation.

---

## Static Assets

Nexus serves global CSS files from `/static/`:

- **`/static/css/global.css`** - Global application styles (BEM classes, theme variables)
- **`/static/css/side-panel.css`** - Navigation panel styles

**Important:** Backend services **must not** include their own CSS files. All styling comes from Nexus's global CSS.

Services should use BEM classes documented in ARCHITECTURE.md Section 10.

### Global CSS Design System

The `global.css` file provides a complete design system using BEM methodology and CSS variables for theming:

#### Components Available:
- **Buttons**: `.btn`, `.btn--primary`, `.btn--secondary`, `.btn--success`, `.btn--danger`, `.btn--warning`, `.btn--small`
- **Cards**: `.card`, `.card__header`, `.card__header-actions`, `.card__body`, `.card__title`
- **Status Text**: `.status-text`, `.status-text--success`, `.status-text--danger`, `.status-text--warning`, `.status-text--info`
- **Modals**: `.modal`, `.modal__dialog`, `.modal__header`, `.modal__body`, `.modal__footer`, `.modal__close`
- **Forms**: `.form-group`, `.form-group__label`, `.form-group__input`, `.form-group__checkbox`
- **Tables**: Standard `<table>` with automatic styling
- **Tabs**: `.tabs`, `.tab`, `.tab--active`, `.tab-content`, `.tab-content--active`
- **Icons**: Uses [Lucide Icons](https://lucide.dev/) loaded via CDN
- **Alerts**: `.alert-box`, `.alert-danger`, `.alert-success`, `.alert-warning`, `.alert-info`
- **Log Components**: `.log-modal`, `.log-entry`, `.log-level`, `.log-container`, `.log-type-selector`
- **Utility Classes**: `.u-mb-1` through `.u-mb-5`, `.u-mt-1` through `.u-mt-5`, `.u-text-center`, `.u-flex`, etc.

#### Theme System:
- Light and dark mode via `[data-theme="dark"]` selector
- CSS variables for all colors (e.g., `var(--color-primary)`, `var(--color-success)`)
- Automatic theme switching based on user preference (stored in Codex)
- All colors adjust automatically when theme changes

#### Icon System:
All pages must include Lucide Icons CDN and initialization:
```html
<head>
    <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body>
    <!-- Your content -->
    <script>
        window.addEventListener('load', () => {
            lucide.createIcons();
        });
    </script>
</body>
```

Common icons used:
- Navigation: `arrow-left`, `arrow-right`
- Actions: `play-circle`, `stop-circle`, `refresh-cw`, `trash-2`, `save`
- Status: `check-circle`, `x-circle`, `alert-triangle`
- UI: `x`, `menu`, `search`, `file-text`, `key`, `lock`

#### CSS Maintenance:
- **DO NOT** add page-specific styles
- **REUSE** existing classes across all pages
- Before adding new CSS, check if a similar class exists
- Use utility classes for spacing instead of custom CSS
- All new styles must work in both light and dark mode

---

## API Endpoints

### Authentication & Session

- `GET /login` - Initiates OAuth2 flow (redirects to Keycloak)
- `GET /keycloak-callback` - OAuth2 callback, exchanges code for JWT
- `GET /logout` - Revokes session at Core, clears cookies, redirects to login

### Keycloak Proxy

- `GET /keycloak/<path>` - Proxies requests to Keycloak server
- Used for OAuth2 endpoints, login pages, resources

### Main Gateway

- `GET /` - Redirects to first accessible service for user's permission level
- `GET /<service>/<path>` - Proxies to backend service with authentication
- `POST/PUT/DELETE /<service>/<path>` - Supports all HTTP methods

### Health Check

- `GET /health` - Returns `{"status": "healthy", "service": "nexus"}`

---

## Development

### Adding New Services

Services are auto-discovered from `services.json`. To add a service:

**Via Helm (Recommended):**
1. Add to `hivematrix-helm/apps_registry.json`
2. Run: `python install_manager.py update-config`
3. Restart Nexus

**Manual:**
1. Edit `services.json`:
   ```json
   {
     "myservice": {
       "url": "http://localhost:5099",
       "visible": true,
       "admin_only": false
     }
   }
   ```

2. Add service icon in `app/routes.py`:
   ```python
   service_icons = {
       'codex': '📚',
       'myservice': '🎯',
   }
   ```

3. Restart Nexus

### Testing Authentication

```bash
# Test without auth (should redirect to login)
curl -v https://localhost:443/codex/

# Test with session cookie
curl -v -b cookies.txt -c cookies.txt https://localhost:443/codex/

# Test backend receives auth header
curl -H "Authorization: Bearer <jwt-token>" http://localhost:5010/
```

Generate test token from Helm:
```bash
cd hivematrix-helm
source pyenv/bin/activate
TOKEN=$(python create_test_token.py 2>/dev/null)
curl -H "Authorization: Bearer $TOKEN" http://localhost:5010/
```

### Debugging

**View Logs:**
```bash
cd hivematrix-helm
source pyenv/bin/activate
python logs_cli.py nexus --tail 50
```

**Check Service Discovery:**
```bash
cat services.json
curl http://localhost:443/health
```

**Test JWT Validation:**
```bash
# Check Core's JWKS endpoint
curl http://localhost:5000/.well-known/jwks.json

# Validate a token
curl -X POST http://localhost:5000/api/token/validate \
  -H "Content-Type: application/json" \
  -d '{"token": "<jwt-token>"}'
```

---

## Security

### Production Deployment

1. **SSL Certificates:** Use Let's Encrypt or commercial certificates
   ```bash
   certbot certonly --standalone -d your-server.com
   cp /etc/letsencrypt/live/your-server.com/fullchain.pem certs/nexus.crt
   cp /etc/letsencrypt/live/your-server.com/privkey.pem certs/nexus.key
   ```

2. **Strong Secret Key:** Generate cryptographically random secret
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Firewall:** Only expose port 443 (HTTPS) externally
   ```bash
   # Allow HTTPS
   sudo ufw allow 443/tcp
   # Block internal service ports
   sudo ufw deny 5000:5999/tcp
   ```

4. **Port 443 Binding:** Grant capability to Python
   ```bash
   sudo setcap cap_net_bind_service=+ep pyenv/bin/python3
   ```

5. **Session Security:**
   - Sessions expire after 1 hour (configurable in Core)
   - Session cookies are HttpOnly, Secure, SameSite=Lax
   - Sessions are revokable (logout revokes immediately)

6. **JWT Security:**
   - Signed with RS256 (RSA asymmetric encryption)
   - Includes session ID (jti) for revocation tracking
   - Validated on every request with Core
   - Expires after 1 hour

7. **Keycloak Security:**
   - Runs on localhost only (not externally accessible)
   - Accessed via Nexus proxy with SSL
   - OAuth2 state parameter prevents CSRF
   - Client secret required for token exchange

### Security Audit

Run security audit from Helm:
```bash
cd hivematrix-helm
source pyenv/bin/activate
python security_audit.py --audit
```

Ensures:
- Nexus binds to 0.0.0.0:443 (external access)
- All backend services bind to 127.0.0.1 (localhost only)
- Firewall blocks direct access to internal services

---

## Troubleshooting

### SSL Certificate Errors in Browser

**Symptom:** Browser shows "Your connection is not private"

**Cause:** Self-signed certificate not trusted

**Solution:**
- Development: Click "Advanced" → "Proceed to localhost"
- Production: Use valid SSL certificate (Let's Encrypt)

### "Service not found" Error

**Check:**
1. Service exists in `services.json`: `cat services.json`
2. Service is running: `curl http://localhost:5010/health`
3. Service URL is correct in `services.json`
4. Restart Nexus to reload configuration

### Infinite Redirect Loop

**Causes:**
1. Core not running: `curl http://localhost:5000/health`
2. Keycloak not running: `curl http://localhost:8080`
3. Wrong `CORE_SERVICE_URL` in `.flaskenv`
4. Stale cookies: Clear browser cookies

**Fix:**
```bash
# Check Core is running
curl http://localhost:5000/health

# Check Keycloak is running
curl http://localhost:8080/health

# Clear cookies and try again
# In browser: DevTools → Application → Clear Site Data
```

### "JSON.parse: unexpected character" Error

**Symptom:** JavaScript error when making AJAX requests

**Cause:** Authentication failed, server returned HTML login page instead of JSON

**Solution:**
1. Add `credentials: 'same-origin'` to all fetch calls:
   ```javascript
   fetch('/codex/api/data', {
       credentials: 'same-origin'
   })
   ```

2. Ensure user is authenticated (has valid session)
3. Check browser console for 401/403 errors

### Side Panel Not Showing

**Check:**
1. Backend service returns HTML with `<body>` tag
2. CSS files exist: `ls -la app/static/css/`
3. Browser dev tools → Network → Check CSS loaded
4. Service response is `Content-Type: text/html`

### Theme Not Saving

**Causes:**
1. User not synced from Keycloak to Codex
2. Codex service not running
3. Missing `credentials: 'same-origin'` in fetch call

**Fix:**
1. Go to Codex → Agents → "🔄 Sync from Keycloak"
2. Check Codex is running: `curl http://localhost:5010/health`
3. Check browser console for errors

### Port 443 Permission Denied

**Symptom:** `Permission denied` when starting on port 443

**Cause:** Non-root user cannot bind to privileged ports (<1024)

**Solution:**
```bash
# Grant capability to Python binary
sudo setcap cap_net_bind_service=+ep pyenv/bin/python3

# Verify capability
getcap pyenv/bin/python3
# Should show: pyenv/bin/python3 = cap_net_bind_service+ep
```

### Gunicorn Not Found

**Symptom:** `gunicorn not found` error

**Solution:**
```bash
source pyenv/bin/activate
pip install gunicorn gevent
```

---

## Configuration Reference

### Environment Variables (`.flaskenv`)

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_APP` | Flask application entry point | `run.py` |
| `FLASK_ENV` | Environment (development/production) | `production` |
| `SECRET_KEY` | Session encryption key (required) | None |
| `SERVICE_NAME` | Service identifier for logging | `nexus` |
| `KEYCLOAK_SERVER_URL` | Keycloak frontend URL | `http://localhost:8080` |
| `KEYCLOAK_BACKEND_URL` | Keycloak backend URL | `http://localhost:8080` |
| `KEYCLOAK_REALM` | Keycloak realm name | `hivematrix` |
| `KEYCLOAK_CLIENT_ID` | OAuth2 client ID | `core-client` |
| `KEYCLOAK_CLIENT_SECRET` | OAuth2 client secret | (from Keycloak) |
| `CORE_SERVICE_URL` | Core service URL | `http://localhost:5000` |
| `NEXUS_SERVICE_URL` | Nexus external URL | `https://localhost:443` |
| `HELM_SERVICE_URL` | Helm service URL | `http://localhost:5004` |
| `NEXUS_PORT` | Port to bind to | `8000` (dev) / `443` (prod) |
| `NEXUS_HOST` | Host to bind to | `0.0.0.0` |
| `USE_GUNICORN` | Use Gunicorn instead of Flask dev server | `true` for port 443 |

### Service Configuration (`services.json`)

```json
{
  "service-name": {
    "url": "http://localhost:PORT",
    "visible": true,              // Show in sidebar
    "admin_only": false,          // Require admin permission
    "billing_or_admin_only": false // Require admin or billing permission
  }
}
```

---

## Related Documentation

- **[HiveMatrix Helm](../hivematrix-helm/README.md)** - Service orchestration and automated setup
- **[Architecture Guide](../hivematrix-helm/ARCHITECTURE.md)** - **READ THIS FIRST** - Complete system architecture
- **[HiveMatrix Core](../hivematrix-core/README.md)** - Authentication and session management
- **[HiveMatrix Codex](../hivematrix-codex/README.md)** - MSP data hub and agent management

---

## License

See main HiveMatrix LICENSE file
