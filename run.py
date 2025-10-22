import os
import sys

# Load .flaskenv before importing app to ensure environment variables are set
from dotenv import load_dotenv
load_dotenv('.flaskenv')

from app import app

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

        # Find gunicorn in venv
        venv_bin = os.path.join(os.path.dirname(__file__), 'pyenv', 'bin')
        gunicorn_path = os.path.join(venv_bin, 'gunicorn')

        if not os.path.exists(gunicorn_path):
            print(f" * ERROR: gunicorn not found at {gunicorn_path}")
            print(f" * Install with: pip install gunicorn")
            sys.exit(1)

        # Build gunicorn command
        # Important: Run Python directly with gunicorn module to preserve capabilities
        # Using the gunicorn wrapper script breaks capability inheritance
        python_path = sys.executable
        cmd = [
            python_path,
            '-m', 'gunicorn',
            '--bind', f'{host}:{port}',
            '--workers', '4',
            '--worker-class', 'gevent',  # Use gevent for SSE streaming support
            '--timeout', '300',  # Longer timeout for SSE connections
            '--access-logfile', '-',
            '--error-logfile', '-',
        ]

        # Add SSL if certs exist and running on 443
        if port == 443 and os.path.exists(cert_file) and os.path.exists(key_file):
            cmd.extend(['--certfile', cert_file])
            cmd.extend(['--keyfile', key_file])
            print(f" * Nexus starting with HTTPS on {host}:{port}", flush=True)
        else:
            print(f" * Nexus starting on http://{host}:{port}", flush=True)

        cmd.append('app:app')
        print(f" * Using Gunicorn WSGI server (production mode)", flush=True)
        print(f" * Command: {' '.join(cmd)}", flush=True)

        # Execute gunicorn via Python to preserve capabilities
        os.execvp(python_path, cmd)
    else:
        # Development mode with Flask's built-in server
        print(f" * Nexus starting on http://{host}:{port}")
        print(f" * Using Flask development server")
        app.run(host=host, port=port, debug=True)
