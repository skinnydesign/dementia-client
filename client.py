"""
Central API client for the Laravel backend.
All modules use this to make authenticated requests.
"""
import requests
from flask import current_app, session


class APIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class LaravelClient:
    """Thin wrapper around requests that injects the Bearer token."""

    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip('/')
        self.timeout  = timeout

    # ── Auth ────────────────────────────────────────────────────────────────────

    def login(self, email: str, password: str, device_name: str = 'flask-client') -> dict:
        """Exchange credentials for a Sanctum token. Returns full response dict."""
        resp = requests.post(
            f'{self.base_url}/token',
            json={'email': email, 'password': password, 'device_name': device_name},
            timeout=self.timeout,
        )
        data = resp.json()
        if not resp.ok:
            raise APIError(data.get('message', 'Login failed'), resp.status_code)
        return data

    def revoke_token(self) -> None:
        self._delete('/token')

    # ── Generic request helpers ──────────────────────────────────────────────────

    def _headers(self) -> dict:
        token = session.get('api_token')
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _url(self, path: str) -> str:
        return f'{self.base_url}/{path.lstrip("/")}'

    def _raise_for(self, resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except Exception:
            data = {'message': resp.text}
        if not resp.ok:
            raise APIError(data.get('message', f'HTTP {resp.status_code}'), resp.status_code)
        return data

    def get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(self._url(path), headers=self._headers(),
                            params=params, timeout=self.timeout)
        return self._raise_for(resp)

    def post(self, path: str, json: dict = None) -> dict:
        resp = requests.post(self._url(path), headers=self._headers(),
                             json=json, timeout=self.timeout)
        return self._raise_for(resp)

    def put(self, path: str, json: dict = None) -> dict:
        resp = requests.put(self._url(path), headers=self._headers(),
                            json=json, timeout=self.timeout)
        return self._raise_for(resp)

    def delete(self, path: str) -> dict:
        resp = requests.delete(self._url(path), headers=self._headers(),
                               timeout=self.timeout)
        return self._raise_for(resp)

    # private alias
    def _delete(self, path: str) -> dict:
        return self.delete(path)


def get_client() -> LaravelClient:
    """Return a client instance configured from the current app."""
    return LaravelClient(
        base_url=current_app.config['API_BASE_URL'],
        timeout=current_app.config['API_TIMEOUT'],
    )
