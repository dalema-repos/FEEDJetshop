from src.diff_engine import (
    canonical_numeric_string,
    diff_categories,
    diff_dynamic_fields,
    diff_product_data,
    diff_stock,
)


def test_diff_product_data():
    current = {"Name": "Old", "Price": "10.0000"}
    desired = {"Name": "New", "Price": "10.0000"}
    diffs = diff_product_data(current, desired, "sv-SE")
    assert len(diffs) == 1
    assert diffs[0].target_field == "Name"


def test_diff_categories():
    diffs = diff_categories(["1", "2"], ["2", "3"], "sv-SE")
    assert len(diffs) == 1
    assert diffs[0].target_field == "ProductInCategories"


def test_diff_stock():
    current = {"NewStockCount": 5}
    desired = {"NewStockCount": 6}
    diffs = diff_stock(current, desired, "sv-SE")
    assert len(diffs) == 1


def test_diff_dynamic_fields():
    current = {"atr_colour": {"sv-SE": "Vit"}}
    desired = {"atr_colour": {"sv-SE": "Hvit"}}
    diffs = diff_dynamic_fields(current, desired)
    assert len(diffs) == 1
    assert diffs[0].target_field == "atr_colour"


def test_diff_numeric_dynamic_field_ignores_insignificant_formatting():
    current = {"atr_height": {"sv-SE": "63"}}
    desired = {"atr_height": {"sv-SE": "63.0"}}

    assert diff_dynamic_fields(current, desired) == []


def test_diff_numeric_dynamic_field_still_detects_value_change():
    current = {"atr_height": {"sv-SE": "63"}}
    desired = {"atr_height": {"sv-SE": "63.5"}}

    diffs = diff_dynamic_fields(current, desired)

    assert len(diffs) == 1
    assert diffs[0].new_value == "63.5"


def test_numeric_dynamic_field_write_format_matches_jetshop_style():
    assert canonical_numeric_string("63.0") == "63"
    assert canonical_numeric_string("63.500") == "63.5"
    assert canonical_numeric_string("0.00") == "0"
    assert canonical_numeric_string("size M") == "size M"


def test_grouping_codes_are_not_treated_as_numeric_measurements():
    current = {"atr_grouping": {"sv-SE": "00123"}}
    desired = {"atr_grouping": {"sv-SE": "123"}}

    assert len(diff_dynamic_fields(current, desired)) == 1
