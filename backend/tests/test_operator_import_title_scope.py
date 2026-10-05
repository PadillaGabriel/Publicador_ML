"""Regression: the middleware must enforce account scope for imports and titles."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.operator_access import operator_access_middleware
from app import operator_account_scope as scope

OWN = uuid.UUID('c2b78a19-1c66-40c3-a948-612987004b73')
FOREIGN = uuid.UUID('ebd1bf6a-3f09-4fd7-befc-7a0de3765530')
OPERATOR = SimpleNamespace(id=uuid.uuid4(), role='OPERATOR')


def request_with_json(path: str, account: uuid.UUID) -> Request:
    import json
    body = json.dumps({'account_id': str(account), 'item_id': 'MLA123456789',
                       'category_id': 'MLA1', 'product_name': 'Prueba', 'max_length': 60}).encode()
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return Request({'type': 'http', 'method': 'POST', 'path': path,
                    'headers': [(b'origin', b'https://publicador.example'),
                                (b'content-type', b'application/json')],
                    'query_string': b'', 'server': ('localhost', 80),
                    'scheme': 'https'}, receive=receive)


@pytest.mark.parametrize('path', ['/api/publication-import/mla',
                                  '/api/publication-import/mla/reuse',
                                  '/api/title-intelligence/generate'])
def test_foreign_account_denied_before_handler(path, monkeypatch):
    monkeypatch.setattr(scope, 'allowed_account_ids', lambda db, user: {OWN})
    called = []
    async def next_handler(request):
        called.append(True)
        raise AssertionError('Must not reach route handler')
    with patch('app.operator_access.SessionLocal'), \
         patch('app.operator_access.request_identity', return_value=(OPERATOR, object())), \
         patch('app.operator_access.same_origin', return_value=True):
        result = asyncio.run(operator_access_middleware(request_with_json(path, FOREIGN), next_handler))
    assert result.status_code == 403
    assert not called


@pytest.mark.parametrize('path', ['/api/publication-import/mla',
                                  '/api/title-intelligence/generate'])
def test_own_account_allowed_by_scope(path, monkeypatch):
    monkeypatch.setattr(scope, 'allowed_account_ids', lambda db, user: {OWN})
    scope.scope_operation(None, OPERATOR, path, 'POST', {}, {'account_id': str(OWN)})


def test_unclassified_title_endpoint_denied():
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, OPERATOR, '/api/title-intelligence/other', 'POST', {},
                              {'account_id': str(OWN)})
    assert exc.value.status_code == 403
