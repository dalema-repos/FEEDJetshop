"""Diff computation for product and dynamic fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


NUMERIC_DYNAMIC_FIELDS = frozenset(
    {
        "atr_height",
        "atr_dia",
        "size",
        "atr_length",
        "atr_kdiao",
        "atr_kdian",
        "atr_kheight",
    }
)


@dataclass(frozen=True)
class DiffItem:
    target_field: str
    old_value: Any
    new_value: Any
    culture: Optional[str] = None
    section: Optional[str] = None


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value:.4f}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonical_numeric_string(value: Any) -> Any:
    """Format numeric dynamic-field values without insignificant trailing zeros."""
    if isinstance(value, bool) or value is None:
        return value
    if not isinstance(value, (str, int, float, Decimal)):
        return value
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return value
    if not number.is_finite():
        return value
    formatted = format(number, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return "0" if formatted in {"", "-0", "+0"} else formatted


def _normalize_dynamic_value(key: str, value: Any) -> Any:
    # Jetshop returns an empty dynamic-field <Value> as None, while an empty
    # string is written as <Value></Value>. Compare these representations as
    # the same missing value to avoid sending the same empty update every run.
    if isinstance(value, str) and value == "":
        return None

    numeric_value = isinstance(value, (str, int, float, Decimal)) and not isinstance(
        value, bool
    )
    if key in NUMERIC_DYNAMIC_FIELDS and numeric_value:
        try:
            number = Decimal(str(value).strip())
            if number.is_finite():
                return number
        except (InvalidOperation, ValueError, TypeError):
            pass
    return _normalize(value)


def diff_product_data(
    current: Dict[str, Any],
    desired: Dict[str, Any],
    culture: Optional[str],
) -> List[DiffItem]:
    diffs: List[DiffItem] = []
    for key, desired_value in desired.items():
        if key in {"ProductInCategories", "StockData"}:
            continue
        current_value = current.get(key)
        if _normalize(current_value) != _normalize(desired_value):
            diffs.append(DiffItem(key, current_value, desired_value, culture=culture, section="ProductData"))
    return diffs


def diff_categories(
    current_categories: List[str],
    desired_categories: List[str],
    culture: Optional[str],
) -> List[DiffItem]:
    current_ids = _normalize_category_ids(current_categories)
    desired_ids = _normalize_category_ids(desired_categories)
    if sorted(current_ids) != sorted(desired_ids):
        return [
            DiffItem(
                "ProductInCategories",
                current_ids,
                desired_ids,
                culture=culture,
                section="Categories",
            )
        ]
    return []


def _normalize_category_ids(categories: List[Any]) -> List[str]:
    normalized: List[str] = []
    for item in categories or []:
        if isinstance(item, dict):
            category_id = item.get("CategoryId")
        else:
            category_id = item
        if category_id is None:
            continue
        normalized.append(str(category_id))
    return normalized


def diff_stock(
    current_stock: Dict[str, Any],
    desired_stock: Dict[str, Any],
    culture: Optional[str],
) -> List[DiffItem]:
    diffs: List[DiffItem] = []
    for key, desired_value in desired_stock.items():
        current_value = current_stock.get(key)
        if _normalize(current_value) != _normalize(desired_value):
            diffs.append(DiffItem(key, current_value, desired_value, culture=culture, section="StockData"))
    return diffs


def diff_dynamic_fields(
    current: Dict[str, Dict[str, Any]],
    desired: Dict[str, Dict[str, Any]],
) -> List[DiffItem]:
    diffs: List[DiffItem] = []
    for key, cultures in desired.items():
        for culture, desired_value in cultures.items():
            current_value = current.get(key, {}).get(culture)
            if _normalize_dynamic_value(
                key, current_value
            ) != _normalize_dynamic_value(key, desired_value):
                diffs.append(
                    DiffItem(
                        target_field=key,
                        old_value=current_value,
                        new_value=desired_value,
                        culture=culture,
                        section="DynamicFields",
                    )
                )
    return diffs
