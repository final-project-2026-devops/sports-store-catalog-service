from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from boto3.dynamodb.conditions import Attr, Key
from fastapi import APIRouter, Depends, HTTPException, Query

from database import products_table, variants_table
from models import ProductCreate, ProductUpdate
from security import require_admin

router = APIRouter(prefix="/products", tags=["products"])


def _decimal_to_float(obj):
    """Recursively convert Decimal values to float for JSON serialisation."""
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _get_variants_for_product(product_id: str) -> list[dict]:
    result = variants_table.query(
        IndexName="product-index",
        KeyConditionExpression=Key("product_id").eq(product_id),
    )
    return result.get("Items", [])


def _attach_variants(product: dict) -> dict:
    product = _decimal_to_float(product)
    variants = _decimal_to_float(_get_variants_for_product(product["product_id"]))
    product["variants"] = [
        {
            "sku": v["sku"],
            "color": v["color"],
            "size": v["size"],
            "price": v["price"],
            "stock_quantity": int(v["stock_quantity"]) if isinstance(v["stock_quantity"], Decimal) else v["stock_quantity"],
        }
        for v in variants
    ]
    if variants:
        product["base_price"] = min(v["price"] for v in product["variants"])
    return product


@router.get("")
async def list_products(
    category: str | None = None,
    gender: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
):
    filter_expr = Attr("is_active").eq(True)
    if category:
        filter_expr = filter_expr & Attr("category").eq(category)
    if gender:
        filter_expr = filter_expr & Attr("gender").eq(gender)
    if tag:
        filter_expr = filter_expr & Attr("tags").contains(tag)
    if q:
        q_lower = q.lower()
        filter_expr = filter_expr & (
            Attr("name").contains(q) | Attr("description").contains(q)
            | Attr("name").contains(q_lower) | Attr("description").contains(q_lower)
        )

    result = products_table.scan(FilterExpression=filter_expr)
    items = result.get("Items", [])

    # Apply skip/limit in Python (DynamoDB scan doesn't support offset)
    items = items[skip: skip + limit]

    products = []
    for product in items:
        products.append(_attach_variants(product))
    return products


@router.get("/{slug}")
async def get_product(slug: str):
    result = products_table.query(
        IndexName="slug-index",
        KeyConditionExpression=Key("slug").eq(slug),
        FilterExpression=Attr("is_active").eq(True),
    )
    items = result.get("Items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Product not found")
    return _attach_variants(items[0])


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def create_product(payload: ProductCreate):
    product_id = str(uuid4())
    variants_data = payload.model_dump().pop("variants") if False else None
    data = payload.model_dump()
    variants_data = data.pop("variants")

    # Check slug uniqueness
    existing = products_table.query(
        IndexName="slug-index",
        KeyConditionExpression=Key("slug").eq(data["slug"]),
    )
    if existing.get("Items"):
        raise HTTPException(status_code=409, detail="Slug or SKU already exists")

    product_item = {
        "product_id": product_id,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **{k: Decimal(str(v)) if isinstance(v, float) else v for k, v in data.items()},
    }
    products_table.put_item(Item=product_item)

    for v in variants_data:
        variant_item = {
            "sku": v["sku"],
            "product_id": product_id,
            "color": v["color"],
            "size": v["size"],
            "price": Decimal(str(v["price"])),
            "stock_quantity": v["stock_quantity"],
        }
        variants_table.put_item(Item=variant_item)

    return {"id": product_id}


@router.put("/{product_id}", dependencies=[Depends(require_admin)])
async def update_product(product_id: str, payload: ProductUpdate):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    variants_data = data.pop("variants", None)

    # Check product exists
    result = products_table.get_item(Key={"product_id": product_id})
    if not result.get("Item"):
        raise HTTPException(status_code=404, detail="Product not found")

    if data:
        update_expr_parts = []
        expr_attr_names = {}
        expr_attr_values = {}
        for i, (k, v) in enumerate(data.items()):
            placeholder = f"#f{i}"
            val_placeholder = f":v{i}"
            expr_attr_names[placeholder] = k
            expr_attr_values[val_placeholder] = Decimal(str(v)) if isinstance(v, float) else v
            update_expr_parts.append(f"{placeholder} = {val_placeholder}")
        products_table.update_item(
            Key={"product_id": product_id},
            UpdateExpression="SET " + ", ".join(update_expr_parts),
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
        )

    if variants_data:
        for v in variants_data:
            variant_item = {
                "sku": v["sku"],
                "product_id": product_id,
                "color": v["color"],
                "size": v["size"],
                "price": Decimal(str(v["price"])),
                "stock_quantity": v["stock_quantity"],
            }
            variants_table.put_item(Item=variant_item)

    return {"message": "Product updated"}


@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
async def delete_product(product_id: str):
    result = products_table.get_item(Key={"product_id": product_id})
    if not result.get("Item"):
        raise HTTPException(status_code=404, detail="Product not found")
    products_table.update_item(
        Key={"product_id": product_id},
        UpdateExpression="SET is_active = :val",
        ExpressionAttributeValues={":val": False},
    )
    return {"message": "Product deactivated"}
