"""
Service-to-Service Authentication Helper for HiveMatrix Nexus

Usage:
    from app.service_client import call_service

    response = call_service('codex', '/api/companies')
"""

import requests
from flask import current_app


def get_service_token(target_service):
    """
    Gets a service token from Core for calling another service.

    Args:
        target_service: The target service name (e.g., 'codex')

    Returns:
        str: JWT service token
    """
    core_url = current_app.config.get('CORE_SERVICE_URL', 'http://localhost:5000')

    token_response = requests.post(
        f"{core_url}/service-token",
        json={
            'calling_service': 'nexus',
            'target_service': target_service
        },
        timeout=5
    )

    if token_response.status_code != 200:
        raise Exception(f"Failed to get service token from Core: {token_response.text}")

    return token_response.json()['token']


def call_service(service_name, path, method='GET', **kwargs):
    """
    Makes an authenticated request to another HiveMatrix service.
    This uses Core to mint a service token for authentication.

    Args:
        service_name: The target service name (e.g., 'codex', 'resolve')
        path: The path to call (e.g., '/api/companies')
        method: HTTP method (default: 'GET')
        **kwargs: Additional arguments to pass to requests.request()

    Returns:
        requests.Response object

    Example:
        response = call_service('codex', '/api/public/user/theme', params={'email': 'user@example.com'})
        data = response.json()
    """
    # Get the service URL from configuration
    services = current_app.config.get('SERVICES', {})
    if service_name not in services:
        raise ValueError(f"Service '{service_name}' not found in configuration")

    service_url = services[service_name]['url']

    # Get a service token from Core
    token = get_service_token(service_name)

    # Make the request with auth header
    url = f"{service_url}{path}"
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {token}'

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        verify=False,  # For self-signed certs in dev
        **kwargs
    )

    return response
