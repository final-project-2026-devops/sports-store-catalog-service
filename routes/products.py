import uuid
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Attr
from fastapi import APIRouter, Depends, HTTPException, Query

from database import decimals_to_number, floats_to_decimal, get_db_table, scan_all_items
from models import ProductCreate, ProductUpdate
from security import require_admin

router = APIRouter(prefix="/products", tags=["products"])


def serialize(item: dict) -> dict:
    return decimals_to_number(item)


@router.get("")
async def list_products(
    category: str | None = None,
    gender: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    table=Depends(get_db_table),
):
    filter_expression = Attr("is_active").eq(True)
    if category:
        filter_expression &= Attr("category").eq(category)
    if gender:
        filter_expression &= Attr("gender").eq(gender)
    if tag:
        filter_expression &= Attr("tags").contains(tag)
    if q:
        # DynamoDB has no full-text index like the removed Mongo $text search —
        # a case-sensitive substring match on name/description is a documented
        # MVP simplification.
        filter_expression &= Attr("name").contains(q) | Attr("description").contains(q)

    items = await scan_all_items(table, filter_expression)
    # scan has no server-side offset/limit semantics that match skip/limit here,
    # so pagination is applied as a Python-level slice over the collected results.
    page = items[skip : skip + limit]
    return [serialize(item) for item in page]


@router.get("/{slug}")
async def get_product(slug: str, table=Depends(get_db_table)):
    filter_expression = Attr("slug").eq(slug) & Attr("is_active").eq(True)
    items = await scan_all_items(table, filter_expression)
    if not items:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize(items[0])


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def create_product(payload: ProductCreate, table=Depends(get_db_table)):
    # No unique indexes on DynamoDB (single PK only) — replicate the old
    # slug/variants.sku uniqueness guarantee with a full-table scan-then-write.
    existing_items = await scan_all_items(table)
    new_skus = {variant.sku for variant in payload.variants}
    for item in existing_items:
        if item.get("slug") == payload.slug:
            raise HTTPException(status_code=409, detail="Slug or SKU already exists")
        for variant in item.get("variants", []):
            if variant.get("sku") in new_skus:
                raise HTTPException(status_code=409, detail="Slug or SKU already exists")

    doc = payload.model_dump()
    doc["item_id"] = str(uuid.uuid4())
    doc["is_active"] = True
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await table.put_item(Item=floats_to_decimal(doc))
    return {"id": doc["item_id"]}


@router.put("/{product_id}", dependencies=[Depends(require_admin)])
async def update_product(product_id: str, payload: ProductUpdate, table=Depends(get_db_table)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    existing = await table.get_item(Key={"item_id": product_id})
    if "Item" not in existing:
        raise HTTPException(status_code=404, detail="Product not found")

    updates = floats_to_decimal(updates)
    # Alias every attribute name (not just the reserved ones, e.g. "name") to
    # sidestep DynamoDB's reserved-word list entirely.
    expression_names = {f"#{key}": key for key in updates}
    expression_values = {f":{key}": value for key, value in updates.items()}
    update_expression = "SET " + ", ".join(f"#{key} = :{key}" for key in updates)

    await table.update_item(
        Key={"item_id": product_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
    )
    return {"message": "Product updated"}


@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
async def delete_product(product_id: str, table=Depends(get_db_table)):
    existing = await table.get_item(Key={"item_id": product_id})
    if "Item" not in existing:
        raise HTTPException(status_code=404, detail="Product not found")

    await table.update_item(
        Key={"item_id": product_id},
        UpdateExpression="SET #is_active = :is_active",
        ExpressionAttributeNames={"#is_active": "is_active"},
        ExpressionAttributeValues={":is_active": False},
    )
    return {"message": "Product deactivated"}
