from decimal import Decimal
from unittest.mock import patch

from botocore.exceptions import ClientError

PRODUCT = {
    "product_id": "p1",
    "name": "Velocity Runner",
    "image_url": "",
    "is_active": True,
}

VARIANT_IN_STOCK = {
    "sku": "VR-BLK-42",
    "product_id": "p1",
    "color": "Black",
    "size": "42",
    "price": Decimal("129.99"),
    "stock_quantity": 15,
}


def test_stock_check_mixed_results(client, auth_headers):
    def get_variant_item(Key):
        if Key.get("sku") == "VR-BLK-42":
            return {"Item": VARIANT_IN_STOCK.copy()}
        return {}

    def get_product_item(Key):
        if Key.get("product_id") == "p1":
            return {"Item": PRODUCT.copy()}
        return {}

    with patch("routes.internal.variants_table") as mock_variants, \
         patch("routes.internal.products_table") as mock_products:
        mock_variants.get_item.side_effect = get_variant_item
        mock_products.get_item.side_effect = get_product_item
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


def test_stock_check_insufficient_quantity(client, auth_headers):
    with patch("routes.internal.variants_table") as mock_variants, \
         patch("routes.internal.products_table") as mock_products:
        mock_variants.get_item.return_value = {
            "Item": {**VARIANT_IN_STOCK, "stock_quantity": 1}
        }
        mock_products.get_item.return_value = {"Item": PRODUCT.copy()}
        response = client.post(
            "/api/internal/stock/check",
            json=[{"sku": "VR-BLK-42", "quantity": 5}],
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()[0]["in_stock"] is False


def test_stock_decrement_success(client, auth_headers):
    with patch("routes.internal.variants_table") as mock_variants:
        mock_variants.update_item.return_value = {}
        response = client.post(
            "/api/internal/stock/decrement",
            json=[{"sku": "VR-BLK-42", "quantity": 2}],
            headers=auth_headers,
        )

    assert response.status_code == 200
    update_kwargs = mock_variants.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"sku": "VR-BLK-42"}
    assert update_kwargs["ExpressionAttributeValues"] == {":neg": -2}


def test_stock_decrement_insufficient_409(client, auth_headers):
    error_response = {
        "Error": {"Code": "ConditionalCheckFailedException", "Message": "boom"}
    }
    with patch("routes.internal.variants_table") as mock_variants:
        mock_variants.update_item.side_effect = ClientError(error_response, "UpdateItem")
        response = client.post(
            "/api/internal/stock/decrement",
            json=[{"sku": "VR-BLK-42", "quantity": 99}],
            headers=auth_headers,
        )

    assert response.status_code == 409
    assert response.json()["detail"]["skus"] == ["VR-BLK-42"]


def test_stock_endpoints_require_token(client):
    response = client.post(
        "/api/internal/stock/check", json=[{"sku": "X", "quantity": 1}]
    )
    assert response.status_code == 401
