"""Regression against an accidental early return before authorization checks."""

import asyncio
from unittest.mock import patch
from starlette.requests import Request
from app.operator_access import operator_access_middleware, required_action


def test_user_management_is_privileged():
    assert required_action('/api/operator-users', 'GET') is None
    assert required_action('/api/operator-users', 'POST') == 'manage_users'
    assert required_action('/api/operator-users/123', 'PATCH') == 'manage_users'


def test_api_without_session_is_denied_before_handler():
    request = Request({'type': 'http', 'method': 'GET', 'path': '/api/accounts',
                       'headers': [], 'query_string': b'', 'server': ('localhost', 80),
                       'scheme': 'http'})
    called = []

    async def next_handler(req):
        called.append(True)
        raise AssertionError('API handler must not be called')

    with patch('app.operator_access.SessionLocal'), patch('app.operator_access.request_identity') as identity:
        from fastapi import HTTPException
        identity.side_effect = HTTPException(status_code=401, detail='Sin sesión')
        result = asyncio.run(operator_access_middleware(request, next_handler))
    assert result.status_code == 401
    assert not called
