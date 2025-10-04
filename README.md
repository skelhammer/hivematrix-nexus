# HiveMatrix Nexus

**API Gateway & UI Composition Layer**

Nexus is the user-facing gateway for the entire HiveMatrix platform. It provides a unified entry point, handles authentication, and composes UIs from multiple backend services.

---

## Quick Start

**For first-time setup of the entire HiveMatrix ecosystem:**

👉 **Start with [hivematrix-helm](../hivematrix-helm/README.md)** 👈

Helm is the orchestration center that will guide you through setting up Keycloak, Core, Nexus, and all other services.

---

## What Nexus Does

- **Smart Reverse Proxy**: Routes requests to appropriate backend services based on URL paths
- **Authentication Gateway**: Enforces authentication for all routes via HiveMatrix Core
- **UI Composition**: Injects global CSS and side panel navigation into backend service UIs
- **Session Management**: Maintains user sessions and JWT tokens
- **Service Discovery**: Automatically discovers backend services via `services.json`

---

## Architecture

See [ARCHITECTURE.md](../hivematrix-helm/ARCHITECTURE.md) for complete system architecture and development guidelines.

### Request Flow

1. User accesses `http://localhost:8000/codex/`
2. Nexus checks for valid session
3. If no session, redirects to Core for authentication
4. After authentication, Core redirects back with JWT
5. Nexus stores JWT in session
6. Nexus proxies request to Codex service at `http://localhost:5010/`
7. Adds `Authorization: Bearer <JWT>` header to proxied request
8. Injects global CSS and side panel into HTML response
9. Returns composed UI to user

---

## Prerequisites

- **Python 3.8+**
- **HiveMatrix Core** running on port 5000
- **Backend services** (Codex, Ledger, KnowledgeTree, etc.)

---

## Installation

### 1. Clone and Setup

```bash
cd /home/david/work/hivematrix-nexus
python3 -m venv pyenv
source pyenv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.flaskenv`:

```bash
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY='a-very-secret-key-for-nexus-sessions'
CORE_SERVICE_URL='http://localhost:5000'
```

### 3. Configure Services

The `services.json` file is automatically synced by Helm from `master_services.json`. It contains the mapping of service names to their URLs:

```json
{
  "helm": {
    "url": "http://localhost:5004"
  },
  "codex": {
    "url": "http://localhost:5010"
  },
  "ledger": {
    "url": "http://localhost:5030"
  },
  "knowledgetree": {
    "url": "http://localhost:5020"
  }
}
```

**Note:** Only services marked as `"visible": true` in Helm's `master_services.json` appear in the Nexus sidebar.

### 4. Run Nexus

```bash
flask run --port=8000
```

Nexus runs on **http://localhost:8000**

---

## How It Works

### Service Routing

Nexus routes requests based on the first path segment:

- `/codex/companies` → `http://localhost:5010/companies`
- `/ledger/invoices` → `http://localhost:5030/invoices`
- `/helm/` → `http://localhost:5004/`

### Authentication Flow

1. User requests `/codex/`
2. No session exists
3. Nexus stores `/codex/` as `next_url`
4. Redirects to `http://localhost:5000/login?next=http://localhost:8000/auth-callback`
5. Core handles Keycloak login
6. Core redirects to `/auth-callback?token=<JWT>`
7. Nexus validates JWT, stores in session
8. Redirects to original `/codex/` URL
9. Proxies request with Authorization header

### UI Composition

For HTML responses, Nexus:
1. Injects `global.css` stylesheet link
2. Injects `side-panel.css` stylesheet link
3. Adds side panel HTML with service navigation
4. Wraps content in layout div
5. Returns composed HTML

### Side Panel

The side panel shows all visible services (from `services.json`) with:
- Service icon
- Service name
- Active state highlighting
- Logout link

---

## Static Assets

Nexus serves global CSS files:

- `/static/css/global.css` - Global application styles (BEM classes)
- `/static/css/side-panel.css` - Navigation panel styles

Backend services **must not** include their own CSS. All styling comes from Nexus.

---

## Development

### Adding New Services

Services are auto-discovered from `services.json`. When Helm starts a service, it automatically syncs the configuration.

To manually add a service:

1. Edit `services.json`:
```json
{
  "myservice": {
    "url": "http://localhost:5099"
  }
}
```

2. Add service icon in `app/routes.py`:
```python
service_icons = {
    'codex': '📚',
    'myservice': '🎯',  # Add your icon
    # ...
}
```

3. Restart Nexus

### Customizing Side Panel

Edit `app/routes.py`, function `inject_side_panel()`:

```python
def inject_side_panel(soup, current_service):
    services = current_app.config.get('SERVICES', {})
    # Modify panel HTML here
    side_panel_html = '''...'''
```

### Testing Authentication

```bash
# Clear cookies and visit
curl -c cookies.txt http://localhost:8000/codex/
# Should redirect to Core login

# After login, check session
curl -b cookies.txt http://localhost:8000/codex/
# Should proxy to Codex with auth header
```

---

## API Endpoints

### Authentication

- `GET /auth-callback` - Receives JWT from Core after successful login
- `GET /logout` - Clears session and redirects to Core logout

### Main Gateway

- `GET /` - Redirects to first available service
- `GET /<service>/<path>` - Proxies to backend service with authentication

---

## Security

- **Session Security**: Use strong random `SECRET_KEY`
- **JWT Validation**: Verifies JWT signature using Core's public key
- **HTTPS**: Use SSL/TLS in production
- **CORS**: Configured via Flask-CORS if needed
- **XSS Protection**: HTML responses are sanitized by BeautifulSoup

---

## Troubleshooting

### "Service not found" error

1. Check `services.json` contains the service
2. Verify service URL is correct
3. Check service is running: `curl http://localhost:5010/health`

### Infinite redirect loop

1. Check Core is running: `curl http://localhost:5000/health`
2. Verify `CORE_SERVICE_URL` in `.flaskenv`
3. Clear browser cookies
4. Check Keycloak is running

### Side panel not showing

1. Verify backend service returns HTML with `<body>` tag
2. Check `static/css/side-panel.css` exists
3. Inspect browser dev tools for CSS errors

### JWT validation fails

1. Check Core's JWKS endpoint: `curl http://localhost:5000/.well-known/jwks.json`
2. Verify JWT hasn't expired
3. Check `issuer` is `hivematrix.core`

---

## Related Documentation

- **[HiveMatrix Helm](../hivematrix-helm/README.md)** - Service orchestration and setup
- **[Architecture Guide](../hivematrix-helm/ARCHITECTURE.md)** - Complete system architecture
- **[HiveMatrix Core](../hivematrix-core/README.md)** - Identity and Access Management

---

## License

See main HiveMatrix LICENSE file
