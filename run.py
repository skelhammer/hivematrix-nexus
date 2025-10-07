from app import app
import os
import sys

if __name__ == "__main__":
    # Nexus is the main entry point
    # Default to port 8000 for manual/dev use
    # Can be overridden via NEXUS_PORT env var (e.g., 443 for production)
    port = int(os.environ.get('NEXUS_PORT', 8000))
    host = os.environ.get('NEXUS_HOST', '0.0.0.0')
    use_gunicorn = os.environ.get('USE_GUNICORN', 'false').lower() == 'true'

    # Use gunicorn for production (especially for port 443 with SSL)
    if use_gunicorn or port == 443:
        cert_dir = os.path.join(os.path.dirname(__file__), 'certs')
        cert_file = os.path.join(cert_dir, 'nexus.crt')
        key_file = os.path.join(cert_dir, 'nexus.key')

        # Build gunicorn command
        cmd = [
            'gunicorn',
            '--bind', f'{host}:{port}',
            '--workers', '4',
            '--timeout', '60',
            '--access-logfile', '-',
            '--error-logfile', '-',
        ]

        # Add SSL if certs exist and running on 443
        if port == 443 and os.path.exists(cert_file) and os.path.exists(key_file):
            cmd.extend(['--certfile', cert_file])
            cmd.extend(['--keyfile', key_file])
            print(f" * Nexus starting with HTTPS on {host}:{port}")
        else:
            print(f" * Nexus starting on http://{host}:{port}")

        cmd.append('app:app')
        print(f" * Using Gunicorn WSGI server (production mode)")

        # Execute gunicorn
        os.execvp('gunicorn', cmd)
    else:
        # Development mode with Flask's built-in server
        print(f" * Nexus starting on http://{host}:{port}")
        print(f" * Using Flask development server")
        app.run(host=host, port=port, debug=True)
