from decimal import Decimal
from unittest.mock import patch

PRODUCT = {
    "product_id": "p1",
    "name": "Velocity Runner",
    "image_url": "/img/velocity.png",
    "is_active": True,
}

VARIANT = {
    "sku": "VR-BLK-42",
    "product_id": "p1",
    "color": "Black",
    "size": "42",
    "price": Decimal("129.99"),
    "stock_quantity": 15,
}


def test_get_variant_snapshot(client, auth_headers):
    with patch("routes.internal.variants_table") as mock_variants, \
         patch("routes.internal.products_table") as mock_products:
        mock_variants.get_item.return_value = {"Item": VARIANT.copy()}
        mock_products.get_item.return_value = {"Item": PRODUCT.copy()}
        response = client.get(
            "/api/internal/variants/VR-BLK-42", headers=auth_headers
        )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": "p1",
        "name": "Velocity Runner",
        "image_url": "/img/velocity.png",
        "sku": "VR-BLK-42",
        "color": "Black",
        "size": "42",
        "price": 129.99,
        "stock_quantity": 15,
    }


def test_get_variant_unknown_sku_404(client, auth_headers):
    with patch("routes.internal.variants_table") as mock_variants:
        mock_variants.get_item.return_value = {}
        response = client.get(
            "/api/internal/variants/GHOST", headers=auth_headers
        )

    assert response.status_code == 404
