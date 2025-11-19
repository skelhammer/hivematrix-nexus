# HiveMatrix Nexus

API gateway and unified frontend for all HiveMatrix services.

## Overview

Nexus is the single entry point for HiveMatrix - it proxies all backend services through one HTTPS port, handles authentication, and injects the global navigation into every page.

**Port:** 443 (HTTPS)

## Features

- **Reverse Proxy** - Routes requests to backend services
- **Authentication** - Handles Keycloak OAuth flow
- **Session Management** - Maintains user sessions and JWT tokens
- **UI Injection** - Adds side panel navigation to all services
- **Theme Support** - Light/dark mode with user preferences
- **Keycloak Proxy** - Exposes Keycloak through Nexus for external access

## Tech Stack

- Flask + Gunicorn
- BeautifulSoup (HTML injection)
- SSL/TLS termination

## Key Endpoints

- `GET /login` - Initiate authentication
- `GET /logout` - End session and revoke token
- `GET /keycloak/*` - Proxy to Keycloak
- `GET /<service>/*` - Proxy to backend service

## Environment Variables

- `CORE_SERVICE_URL` - Core service URL
- `KEYCLOAK_SERVER_URL` - External Keycloak URL
- `KEYCLOAK_BACKEND_URL` - Internal Keycloak URL
- `KEYCLOAK_REALM` - Keycloak realm
- `KEYCLOAK_CLIENT_ID` - OAuth client ID
- `KEYCLOAK_CLIENT_SECRET` - OAuth client secret
- `SECRET_KEY` - Flask session secret

## SSL Configuration

Requires SSL certificates in the `certs/` directory:
- `server.crt` - SSL certificate
- `server.key` - SSL private key

## Documentation

For complete installation, configuration, and architecture documentation:

**[HiveMatrix Documentation](https://skelhammer.github.io/hivematrix-docs/)**

## License

MIT License - See LICENSE file
