import os
from decimal import Decimal

import aioboto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]

session = aioboto3.Session()


async def get_db_table():
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_NAME)
        yield table


def floats_to_decimal(value):
    """Recursively convert Python floats to Decimal for DynamoDB writes.

    boto3 raises TypeError on raw floats, so every product doc must pass
    through this before a put_item/update_item call.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [floats_to_decimal(v) for v in value]
    return value


def decimals_to_number(value):
    """Recursively convert DynamoDB Decimals back to plain float/int for JSON responses."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: decimals_to_number(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimals_to_number(v) for v in value]
    return value


async def scan_all_items(table, filter_expression=None):
    """Scan the whole table, paginating through LastEvaluatedKey until exhausted.

    There are no secondary indexes in this schema, so every non-key lookup
    goes through this — a single scan call caps at ~1MB, so results must be
    collected across pages before any filtering/slicing happens in Python.
    """
    items = []
    scan_kwargs = {}
    if filter_expression is not None:
        scan_kwargs["FilterExpression"] = filter_expression
    while True:
        response = await table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return items
