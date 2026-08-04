from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

PRODUCT_ID = "9f8c5e10-1111-4444-8888-abcdefabcdef"

SAMPLE_PRODUCT = {
    "product_id": PRODUCT_ID,
    "name": "Velocity Runner",
    "slug": "velocity-runner",
    "description": "Lightweight running shoe",
    "brand": "Stryda",
    "category": "running-shoes",
    "gender": "men",
    "tags": ["running", "lightweight"],
    "image_url": "",
    "is_active": True,
}

SAMPLE_VARIANT = {
    "sku": "VR-BLK-42",
    "product_id": PRODUCT_ID,
    "color": "Black",
    "size": "42",
    "price": Decimal("129.99"),
    "stock_quantity": 15,
}

NEW_PRODUCT = {
    "name": "Court Master Pro",
    "slug": "court-master-pro",
    "category": "basketball-shoes",
    "base_price": 149.99,
    "variants": [
        {"sku": "CM-WHT-43", "color": "White", "size": "43",
         "price": 149.99, "stock_quantity": 10},
    ],
}


def test_list_products_returns_products_with_variants(client):
    with patch("routes.products.products_table") as mock_products, \
         patch("routes.products.variants_table") as mock_variants:
        mock_products.scan.return_value = {"Items": [SAMPLE_PRODUCT.copy()]}
        mock_variants.query.return_value = {"Items": [SAMPLE_VARIANT.copy()]}
        response = client.get(
            "/api/products?category=running-shoes&gender=men&tag=running&q=velocity"
        )

    assert response.status_code == 200
    body = response.json()
    assert body[0]["slug"] == "velocity-runner"
    assert body[0]["variants"][0]["sku"] == "VR-BLK-42"
    mock_products.scan.assert_called_once()
    assert "FilterExpression" in mock_products.scan.call_args.kwargs


def test_list_products_empty(client):
    with patch("routes.products.products_table") as mock_products:
        mock_products.scan.return_value = {"Items": []}
        response = client.get("/api/products")

    assert response.status_code == 200
    assert response.json() == []


def test_get_product_by_slug(client):
    with patch("routes.products.products_table") as mock_products, \
         patch("routes.products.variants_table") as mock_variants:
        mock_products.query.return_value = {"Items": [SAMPLE_PRODUCT.copy()]}
        mock_variants.query.return_value = {"Items": [SAMPLE_VARIANT.copy()]}
        response = client.get("/api/products/velocity-runner")

    assert response.status_code == 200
    assert response.json()["name"] == "Velocity Runner"


def test_get_product_unknown_slug_404(client):
    with patch("routes.products.products_table") as mock_products:
        mock_products.query.return_value = {"Items": []}
        response = client.get("/api/products/nope")

    assert response.status_code == 404


def test_create_product_as_admin(client, admin_headers):
    fixed_id = UUID("11111111-1111-1111-1111-111111111111")
    with patch("routes.products.uuid4", return_value=fixed_id), \
         patch("routes.products.products_table") as mock_products, \
         patch("routes.products.variants_table") as mock_variants:
        mock_products.query.return_value = {"Items": []}
        response = client.post(
            "/api/products", json=NEW_PRODUCT, headers=admin_headers
        )

    assert response.status_code == 201
    assert response.json() == {"id": str(fixed_id)}
    mock_products.put_item.assert_called_once()
    mock_variants.put_item.assert_called_once()


def test_create_product_duplicate_slug_409(client, admin_headers):
    with patch("routes.products.products_table") as mock_products, \
         patch("routes.products.variants_table"):
        mock_products.query.return_value = {"Items": [SAMPLE_PRODUCT.copy()]}
        response = client.post(
            "/api/products", json=NEW_PRODUCT, headers=admin_headers
        )

    assert response.status_code == 409


def test_create_product_as_customer_403(client, auth_headers):
    response = client.post("/api/products", json=NEW_PRODUCT, headers=auth_headers)
    assert response.status_code == 403


def test_create_product_anonymous_401(client):
    response = client.post("/api/products", json=NEW_PRODUCT)
    assert response.status_code == 401


def test_delete_product_soft_deletes(client, admin_headers):
    with patch("routes.products.products_table") as mock_products:
        mock_products.get_item.return_value = {"Item": SAMPLE_PRODUCT.copy()}
        response = client.delete(
            f"/api/products/{PRODUCT_ID}", headers=admin_headers
        )

    assert response.status_code == 200
    update_kwargs = mock_products.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"product_id": PRODUCT_ID}
    assert update_kwargs["ExpressionAttributeValues"] == {":val": False}


def test_delete_product_404_when_missing(client, admin_headers):
    with patch("routes.products.products_table") as mock_products:
        mock_products.get_item.return_value = {}
        response = client.delete(
            f"/api/products/{PRODUCT_ID}", headers=admin_headers
        )

    assert response.status_code == 404


def test_update_product_404_when_missing(client, admin_headers):
    with patch("routes.products.products_table") as mock_products:
        mock_products.get_item.return_value = {}
        response = client.put(
            f"/api/products/{PRODUCT_ID}",
            json={"base_price": 99.99},
            headers=admin_headers,
        )

    assert response.status_code == 404
