from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError


def product_doc(sku="VR-BLK-42", stock=15, item_id="prod-1"):
    return {
        "item_id": item_id,
        "name": "Velocity Runner",
        "is_active": True,
        "variants": [{"sku": sku, "stock_quantity": stock}],
    }


def test_stock_check_mixed_results(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=15)]})

    response = client.post(
        "/api/internal/stock/check",
        json=[
            {"sku": "VR-BLK-42", "quantity": 2},
            {"sku": "GHOST-SKU", "quantity": 1},
        ],
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == [
        {"sku": "VR-BLK-42", "available": 15, "in_stock": True},
        {"sku": "GHOST-SKU", "available": 0, "in_stock": False},
    ]


def test_stock_check_insufficient_quantity(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=1)]})

    response = client.post(
        "/api/internal/stock/check",
        json=[{"sku": "VR-BLK-42", "quantity": 5}],
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["in_stock"] is False


def test_stock_decrement_success(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=15, item_id="prod-1")]})
    mock_table.update_item = AsyncMock(return_value={})

    response = client.post(
        "/api/internal/stock/decrement",
        json=[{"sku": "VR-BLK-42", "quantity": 2}],
        headers=auth_headers,
    )

    assert response.status_code == 200
    update_kwargs = mock_table.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"item_id": "prod-1"}
    assert "variants[0].stock_quantity" in update_kwargs["UpdateExpression"]
    assert update_kwargs["ConditionExpression"] == "variants[0].stock_quantity >= :qty"
    assert update_kwargs["ExpressionAttributeValues"] == {":qty": Decimal("2")}


def test_stock_decrement_sku_not_found_409(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=15)]})

    response = client.post(
        "/api/internal/stock/decrement",
        json=[{"sku": "GHOST-SKU", "quantity": 1}],
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["skus"] == ["GHOST-SKU"]
    mock_table.update_item.assert_not_awaited()


def test_stock_decrement_insufficient_409(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=15, item_id="prod-1")]})
    mock_table.update_item = AsyncMock(
        side_effect=ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "nope"}},
            "UpdateItem",
        )
    )

    response = client.post(
        "/api/internal/stock/decrement",
        json=[{"sku": "VR-BLK-42", "quantity": 99}],
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["skus"] == ["VR-BLK-42"]


def test_stock_decrement_reraises_unexpected_client_error(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [product_doc(stock=15, item_id="prod-1")]})
    mock_table.update_item = AsyncMock(
        side_effect=ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "nope"}},
            "UpdateItem",
        )
    )

    with pytest.raises(ClientError):
        client.post(
            "/api/internal/stock/decrement",
            json=[{"sku": "VR-BLK-42", "quantity": 1}],
            headers=auth_headers,
        )


def test_stock_endpoints_require_token(client):
    response = client.post(
        "/api/internal/stock/check", json=[{"sku": "X", "quantity": 1}]
    )
    assert response.status_code == 401
