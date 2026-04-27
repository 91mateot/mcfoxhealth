"""DynamoDB helpers — thin wrappers around boto3 resource API."""

import os
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

_resource = None


def _get_resource():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def get_table(env_var: str):
    name = os.environ.get(env_var)
    if not name:
        raise ValueError(f"Missing env var: {env_var}")
    return _get_resource().Table(name)


def _to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _from_decimal(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(v) for v in obj]
    return obj


def put_item(table, item: dict) -> None:
    table.put_item(Item=_to_decimal(item))


def get_item(table, key: dict) -> Optional[dict]:
    resp = table.get_item(Key=key)
    item = resp.get("Item")
    return _from_decimal(item) if item else None


def query_items(
    table,
    pk_name: str,
    pk_value: str,
    sk_name: Optional[str] = None,
    sk_begins: Optional[str] = None,
    sk_between: Optional[tuple] = None,
    limit: Optional[int] = None,
    reverse: bool = False,
) -> list[dict]:
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key(pk_name).eq(pk_value),
        "ScanIndexForward": not reverse,
    }

    if sk_name and sk_begins:
        kwargs["KeyConditionExpression"] &= Key(sk_name).begins_with(sk_begins)
    elif sk_name and sk_between:
        kwargs["KeyConditionExpression"] &= Key(sk_name).between(*sk_between)

    if limit:
        kwargs["Limit"] = limit

    resp = table.query(**kwargs)
    return [_from_decimal(i) for i in resp.get("Items", [])]


def batch_write(table, items: list[dict]) -> None:
    with table.batch_writer() as writer:
        for item in items:
            writer.put_item(Item=_to_decimal(item))
