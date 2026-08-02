import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

os.environ["JWT_SECRET"] = "test-secret"
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-table")

import jwt
import pytest
from fastapi.testclient import TestClient

from database import get_db_table
from main import app


def make_token(user_id="507f1f77bcf86cd799439011", email="user@test.com",
               role="customer", expires_minutes=60):
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


@pytest.fixture
def mock_table():
    """AsyncMock standing in for the aioboto3 DynamoDB Table resource.

    Defaults produce empty/absent results; individual tests override the
    relevant method's return_value/side_effect for their scenario.
    """
    table = AsyncMock()
    table.scan = AsyncMock(return_value={"Items": []})
    table.get_item = AsyncMock(return_value={})
    table.put_item = AsyncMock(return_value={})
    table.update_item = AsyncMock(return_value={})
    return table


@pytest.fixture
def client(mock_table):
    async def override_get_db_table():
        yield mock_table

    app.dependency_overrides[get_db_table] = override_get_db_table
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_table, None)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {make_token(role='admin')}"}
