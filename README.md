# HiveMatrix Nexus

Nexus is the user-facing gateway and UI Compositor for the entire HiveMatrix platform. It acts as a smart reverse proxy that performs two critical functions:

1.  **Service Routing:** It uses `services.json` to route requests to the appropriate backend application (e.g., a request to `/template/...` is forwarded to the `hivematrix-template` service).

2.  **UI Composition:** It injects a global stylesheet into any HTML responses returned by a backend service, providing a consistent look and feel across the entire platform.


## Running the Service

1.  Create a virtual environment: `python -m venv pyenv`

2.  Activate it: `source pyenv/bin/activate`

3.  Install dependencies: `pip install -r requirements.txt`

4.  Run the app: `flask run --port=8000`


## Setup .flaskenv
```
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY='a-very-secret-key-for-nexus-sessions'
CORE_SERVICE_URL='http://localhost:5000'
```

The service will be available at `http://localhost:8000`.
