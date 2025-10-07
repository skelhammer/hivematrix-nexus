from app import app
import os

if __name__ == "__main__":
    # Nexus is the main entry point
    # Default to port 8000 for manual/dev use
    # Can be overridden via NEXUS_PORT env var (e.g., 443 for production)
    port = int(os.environ.get('NEXUS_PORT', 8000))
    host = os.environ.get('NEXUS_HOST', '0.0.0.0')
    use_waitress = os.environ.get('USE_WAITRESS', 'false').lower() == 'true'

    # Use waitress for production (especially for port 443)
    if use_waitress or port == 443:
        from waitress import serve

        print(f" * Nexus starting on http://{host}:{port}")
        print(f" * Using Waitress WSGI server (production mode)")
        if port == 443:
            print(f" * Note: Running HTTP on port 443")
            print(f" * For SSL, place nginx/caddy reverse proxy in front")

        serve(app, host=host, port=port, threads=4, channel_timeout=60)
    else:
        # Development mode with Flask's built-in server
        print(f" * Nexus starting on http://{host}:{port}")
        print(f" * Using Flask development server")
        app.run(host=host, port=port, debug=True)
