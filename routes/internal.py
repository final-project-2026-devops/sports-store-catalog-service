from decimal import Decimal

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException

from database import products_table, variants_table
from models import StockItem
from security import get_current_user

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(get_current_user)],
)


def _decimal_to_native(obj):
    """Recursively convert Decimal values to int/float for JSON serialisation."""
    if isinstance(obj, list):
        return [_decimal_to_native(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        f = float(obj)
        return int(f) if f == int(f) else f
    return obj


def _get_variant(sku: str) -> tuple[dict | None, dict | None]:
    """Return (variant_item, product_item) or (None, None) if not found."""
    result = variants_table.get_item(Key={"sku": sku})
    variant = result.get("Item")
    if variant is None:
        return None, None
    product_result = products_table.get_item(Key={"product_id": variant["product_id"]})
    product = product_result.get("Item")
    if product is None or not product.get("is_active", False):
        return None, None
    return variant, product


@router.get("/variants/{sku}")
async def get_variant(sku: str):
    variant, product = _get_variant(sku)
    if variant is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    return _decimal_to_native({
        "product_id": variant["product_id"],
        "name": product["name"],
        "image_url": product.get("image_url", ""),
        "sku": variant["sku"],
        "color": variant["color"],
        "size": variant["size"],
        "price": variant["price"],
        "stock_quantity": variant["stock_quantity"],
    })


@router.post("/stock/check")
async def check_stock(items: list[StockItem]):
    results = []
    for item in items:
        variant, product = _get_variant(item.sku)
        available = int(variant["stock_quantity"]) if variant else 0
        results.append(
            {
                "sku": item.sku,
                "available": available,
                "in_stock": available >= item.quantity,
            }
        )
    return results


@router.post("/stock/decrement")
async def decrement_stock(items: list[StockItem]):
    failed = []
    for item in items:
        try:
            variants_table.update_item(
                Key={"sku": item.sku},
                UpdateExpression="ADD stock_quantity :neg",
                ConditionExpression=Attr("stock_quantity").gte(item.quantity),
                ExpressionAttributeValues={":neg": -item.quantity},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                failed.append(item.sku)
            else:
                raise
    if failed:
        raise HTTPException(
            status_code=409,
            detail={"message": "Insufficient stock", "skus": failed},
        )
    return {"message": "Stock decremented"}
