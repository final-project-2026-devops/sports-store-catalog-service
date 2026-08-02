from unittest.mock import AsyncMock

PRODUCT_DOC = {
    "item_id": "507f1f77bcf86cd799439021",
    "name": "Velocity Runner",
    "image_url": "/img/velocity.png",
    "is_active": True,
    "variants": [
        {"sku": "VR-BLK-42", "color": "Black", "size": "42",
         "price": 129.99, "stock_quantity": 15},
    ],
}


def test_get_variant_snapshot(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [PRODUCT_DOC.copy()]})
    response = client.get(
        "/api/internal/variants/VR-BLK-42", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": "507f1f77bcf86cd799439021",
        "name": "Velocity Runner",
        "image_url": "/img/velocity.png",
        "sku": "VR-BLK-42",
        "color": "Black",
        "size": "42",
        "price": 129.99,
        "stock_quantity": 15,
    }


def test_get_variant_unknown_sku_404(client, mock_table, auth_headers):
    mock_table.scan = AsyncMock(return_value={"Items": [PRODUCT_DOC.copy()]})
    response = client.get(
        "/api/internal/variants/GHOST", headers=auth_headers
    )

    assert response.status_code == 404
