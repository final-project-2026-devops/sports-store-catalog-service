import uuid
from unittest.mock import AsyncMock

from boto3.dynamodb.conditions import ConditionBase

PRODUCT_ID = str(uuid.uuid4())

SAMPLE_PRODUCT = {
    "item_id": PRODUCT_ID,
    "name": "Velocity Runner",
    "slug": "velocity-runner",
    "description": "Lightweight running shoe",
    "brand": "Stryda",
    "category": "running-shoes",
    "gender": "men",
    "tags": ["running", "lightweight"],
    "image_url": "",
    "base_price": 129.99,
    "variants": [
        {"sku": "VR-BLK-42", "color": "Black", "size": "42",
         "price": 129.99, "stock_quantity": 15},
    ],
    "is_active": True,
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


def flatten_condition(cond):
    """Flatten a boto3 dynamodb Attr condition tree into (attr_name, operator, value) leaves."""
    expr = cond.get_expression()
    values = expr["values"]
    if all(isinstance(v, ConditionBase) for v in values):
        leaves = []
        for v in values:
            leaves.extend(flatten_condition(v))
        return leaves
    attr, value = values
    return [(attr.name, expr["operator"], value)]


def test_list_products_builds_filter_query(client, mock_table):
    mock_table.scan = AsyncMock(return_value={"Items": [SAMPLE_PRODUCT.copy()]})
    response = client.get(
        "/api/products?category=running-shoes&gender=men&tag=running&q=velocity"
    )

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "velocity-runner"

    filter_expression = mock_table.scan.call_args.kwargs["FilterExpression"]
    leaves = flatten_condition(filter_expression)
    assert ("is_active", "=", True) in leaves
    assert ("category", "=", "running-shoes") in leaves
    assert ("gender", "=", "men") in leaves
    assert ("tags", "contains", "running") in leaves
    assert ("name", "contains", "velocity") in leaves
    assert ("description", "contains", "velocity") in leaves


def test_list_products_empty(client, mock_table):
    mock_table.scan = AsyncMock(return_value={"Items": []})
    response = client.get("/api/products")

    assert response.status_code == 200
    assert response.json() == []


def test_list_products_paginates_scan_results(client, mock_table):
    # scan has no server-side skip/limit — the app must paginate via
    # LastEvaluatedKey and then apply skip/limit as a Python-level slice.
    page_1 = {
        "Items": [{**SAMPLE_PRODUCT, "item_id": "id-1", "slug": "p1"}],
        "LastEvaluatedKey": {"item_id": "id-1"},
    }
    page_2 = {"Items": [{**SAMPLE_PRODUCT, "item_id": "id-2", "slug": "p2"}]}
    mock_table.scan = AsyncMock(side_effect=[page_1, page_2])

    response = client.get("/api/products")

    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert slugs == ["p1", "p2"]
    assert mock_table.scan.call_count == 2
    assert mock_table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"item_id": "id-1"}


def test_list_products_applies_skip_and_limit(client, mock_table):
    items = [{**SAMPLE_PRODUCT, "item_id": f"id-{i}", "slug": f"p{i}"} for i in range(5)]
    mock_table.scan = AsyncMock(return_value={"Items": items})

    response = client.get("/api/products?skip=2&limit=2")

    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert slugs == ["p2", "p3"]


def test_get_product_by_slug(client, mock_table):
    mock_table.scan = AsyncMock(return_value={"Items": [SAMPLE_PRODUCT.copy()]})
    response = client.get("/api/products/velocity-runner")

    assert response.status_code == 200
    assert response.json()["name"] == "Velocity Runner"


def test_get_product_unknown_slug_404(client, mock_table):
    mock_table.scan = AsyncMock(return_value={"Items": []})
    response = client.get("/api/products/nope")

    assert response.status_code == 404


def test_create_product_as_admin(client, mock_table, admin_headers):
    mock_table.scan = AsyncMock(return_value={"Items": []})
    mock_table.put_item = AsyncMock(return_value={})

    response = client.post(
        "/api/products", json=NEW_PRODUCT, headers=admin_headers
    )

    assert response.status_code == 201
    new_id = response.json()["id"]
    uuid.UUID(new_id)  # raises if not a valid uuid string

    put_kwargs = mock_table.put_item.call_args.kwargs
    item = put_kwargs["Item"]
    assert item["slug"] == "court-master-pro"
    assert item["item_id"] == new_id
    assert item["is_active"] is True


def test_create_product_duplicate_slug_409(client, mock_table, admin_headers):
    mock_table.scan = AsyncMock(
        return_value={"Items": [{**SAMPLE_PRODUCT, "slug": "court-master-pro"}]}
    )

    response = client.post(
        "/api/products", json=NEW_PRODUCT, headers=admin_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Slug or SKU already exists"
    mock_table.put_item.assert_not_awaited()


def test_create_product_duplicate_sku_409(client, mock_table, admin_headers):
    conflicting = {
        **SAMPLE_PRODUCT,
        "slug": "some-other-slug",
        "variants": [{"sku": "CM-WHT-43", "color": "Red", "size": "40",
                      "price": 10.0, "stock_quantity": 1}],
    }
    mock_table.scan = AsyncMock(return_value={"Items": [conflicting]})

    response = client.post(
        "/api/products", json=NEW_PRODUCT, headers=admin_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Slug or SKU already exists"
    mock_table.put_item.assert_not_awaited()


def test_create_product_as_customer_403(client, auth_headers):
    response = client.post("/api/products", json=NEW_PRODUCT, headers=auth_headers)
    assert response.status_code == 403


def test_create_product_anonymous_401(client):
    response = client.post("/api/products", json=NEW_PRODUCT)
    assert response.status_code == 401


def test_delete_product_soft_deletes(client, mock_table, admin_headers):
    mock_table.get_item = AsyncMock(return_value={"Item": SAMPLE_PRODUCT.copy()})
    mock_table.update_item = AsyncMock(return_value={})

    response = client.delete(
        f"/api/products/{PRODUCT_ID}", headers=admin_headers
    )

    assert response.status_code == 200
    update_kwargs = mock_table.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"item_id": PRODUCT_ID}
    assert update_kwargs["ExpressionAttributeValues"] == {":is_active": False}


def test_delete_product_404_when_missing(client, mock_table, admin_headers):
    mock_table.get_item = AsyncMock(return_value={})

    response = client.delete(
        f"/api/products/{PRODUCT_ID}", headers=admin_headers
    )

    assert response.status_code == 404
    mock_table.update_item.assert_not_awaited()


def test_update_product_404_when_missing(client, mock_table, admin_headers):
    mock_table.get_item = AsyncMock(return_value={})

    response = client.put(
        f"/api/products/{PRODUCT_ID}",
        json={"base_price": 99.99},
        headers=admin_headers,
    )

    assert response.status_code == 404
    mock_table.update_item.assert_not_awaited()


def test_update_product_success(client, mock_table, admin_headers):
    mock_table.get_item = AsyncMock(return_value={"Item": SAMPLE_PRODUCT.copy()})
    mock_table.update_item = AsyncMock(return_value={})

    response = client.put(
        f"/api/products/{PRODUCT_ID}",
        json={"base_price": 99.99},
        headers=admin_headers,
    )

    assert response.status_code == 200
    update_kwargs = mock_table.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"item_id": PRODUCT_ID}
    assert update_kwargs["ExpressionAttributeNames"] == {"#base_price": "base_price"}
    from decimal import Decimal
    assert update_kwargs["ExpressionAttributeValues"] == {":base_price": Decimal("99.99")}


def test_update_product_no_fields_400(client, mock_table, admin_headers):
    response = client.put(
        f"/api/products/{PRODUCT_ID}",
        json={},
        headers=admin_headers,
    )

    assert response.status_code == 400
    mock_table.get_item.assert_not_awaited()
