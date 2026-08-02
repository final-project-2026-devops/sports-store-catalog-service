from decimal import Decimal

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException

from database import decimals_to_number, get_db_table, scan_all_items
from models import StockItem
from security import get_current_user

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(get_current_user)],
)


def find_variant(doc: dict | None, sku: str) -> dict | None:
    if doc is None:
        return None
    return next((v for v in doc["variants"] if v["sku"] == sku), None)


@router.get("/variants/{sku}")
async def get_variant(sku: str, table=Depends(get_db_table)):
    items = await scan_all_items(table, Attr("is_active").eq(True))
    doc = None
    variant = None
    for item in items:
        variant = find_variant(item, sku)
        if variant is not None:
            doc = item
            break
    if variant is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    doc = decimals_to_number(doc)
    variant = decimals_to_number(variant)
    return {
        "product_id": doc["item_id"],
        "name": doc["name"],
        "image_url": doc.get("image_url", ""),
        "sku": variant["sku"],
        "color": variant["color"],
        "size": variant["size"],
        "price": variant["price"],
        "stock_quantity": variant["stock_quantity"],
    }


@router.post("/stock/check")
async def check_stock(items: list[StockItem], table=Depends(get_db_table)):
    results = []
    for item in items:
        docs = await scan_all_items(table, Attr("is_active").eq(True))
        variant = None
        for doc in docs:
            variant = find_variant(doc, item.sku)
            if variant is not None:
                break
        available = decimals_to_number(variant["stock_quantity"]) if variant else 0
        results.append(
            {
                "sku": item.sku,
                "available": available,
                "in_stock": available >= item.quantity,
            }
        )
    return results


@router.post("/stock/decrement")
async def decrement_stock(items: list[StockItem], table=Depends(get_db_table)):
    # No rollback of earlier items on partial failure — an accepted MVP gap
    # (see README: reservations/sagas are the Phase 2 exercise).
    failed = []
    for item in items:
        docs = await scan_all_items(table)
        target_item_id = None
        target_index = None
        for doc in docs:
            for index, variant in enumerate(doc.get("variants", [])):
                if variant["sku"] == item.sku:
                    target_item_id = doc["item_id"]
                    target_index = index
                    break
            if target_item_id is not None:
                break

        if target_item_id is None:
            failed.append(item.sku)
            continue

        try:
            await table.update_item(
                Key={"item_id": target_item_id},
                UpdateExpression=(
                    f"SET variants[{target_index}].stock_quantity = "
                    f"variants[{target_index}].stock_quantity - :qty"
                ),
                ConditionExpression=f"variants[{target_index}].stock_quantity >= :qty",
                ExpressionAttributeValues={":qty": Decimal(str(item.quantity))},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                failed.append(item.sku)
            else:
                raise

    if failed:
        raise HTTPException(
            status_code=409,
            detail={"message": "Insufficient stock", "skus": failed},
        )
    return {"message": "Stock decremented"}
