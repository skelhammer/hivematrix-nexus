from app import app
import os
import ssl

if __name__ == "__main__":
    # Nexus is the main entry point
    # Default to port 8000 for manual/dev use
    # Can be overridden via NEXUS_PORT env var (e.g., 443 for production)
    port = int(os.environ.get('NEXUS_PORT', 8000))
    host = os.environ.get('NEXUS_HOST', '0.0.0.0')

    # Use SSL if running on port 443
    if port == 443:
        cert_dir = os.path.join(os.path.dirname(__file__), 'certs')
        cert_file = os.path.join(cert_dir, 'nexus.crt')
        key_file = os.path.join(cert_dir, 'nexus.key')

        if os.path.exists(cert_file) and os.path.exists(key_file):
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_file, key_file)
            print(f" * Running with SSL on https://{host}:{port}")
            app.run(host=host, port=port, ssl_context=ssl_context)
        else:
            print(f" * WARNING: SSL certificates not found, falling back to HTTP")
            app.run(host=host, port=port)
    else:
        app.run(host=host, port=port)
