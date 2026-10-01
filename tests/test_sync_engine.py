import copy
import logging
from pathlib import Path
from datetime import datetime


from src.jetshop_client import NIL_VALUE
from src.mapping_loader import load_mapping
from src.state_store import StateStore
from src.sync_engine import SyncEngine


def build_sample_product():
    return {
        "identifier": {"productNo": "Pelle-1092-10"},
        "attributes": [
            {"importCode": "monitor_disp", "dataType": "FLOAT", "value": 10.0},
            {"importCode": "monitor_GTIN", "dataType": "UNI_TEXT", "value": "123"},
            {"importCode": "b2c_price_se", "dataType": "FLOAT", "value": 100.0},
            {"importCode": "b2c_price_no", "dataType": "FLOAT", "value": 110.0},
            {"importCode": "b2c_price_b2b", "dataType": "FLOAT", "value": 120.0},
            {"importCode": "se_show_mp", "dataType": "BOOLEAN", "value": True},
            {"importCode": "no_show_mp", "dataType": "BOOLEAN", "value": True},
            {"importCode": "b2b_show_mp", "dataType": "BOOLEAN", "value": True},
            {"importCode": "monitor_deliverydate", "dataType": "DATE", "value": "2025-01-02T00:00:00"},
            {
                "importCode": "jetshop_category_mp",
                "dataType": "DATA_REGISTER_MULTI",
                "value": ["150", "151"],
            },
            {"importCode": "atr_height", "dataType": "FLOAT", "value": 63},
            {
                "importCode": "atr_colour",
                "dataType": "DATA_REGISTER",
                "options": {"4": {"sv": "Vit", "nb": "Hvit"}},
                "value": "4",
            },
            {"importCode": "atr_grouping", "dataType": "UNI_TEXT", "value": "Group"},
            {"importCode": "spec_cat", "dataType": "UNI_TEXT", "value": {"sv": "SpecCat", "nb": "SpecCatNb"}},
            {
                "importCode": "spec_subcat",
                "dataType": "UNI_TEXT",
                "value": {"sv": "SpecSub", "nb": "SpecSubNb"},
            },
        ],
        "texts": [
            {"importCode": "name_1", "value": {"sv": "Nigella", "nb": "Jomfru"}, "maxLength": 200},
            {"importCode": "name_2", "value": {"sv": "", "nb": ""}, "maxLength": 200},
            {"importCode": "productinfoshort", "value": {"sv": "Short", "nb": "Short nb"}, "maxLength": 300},
            {"importCode": "productinfolong", "value": {"sv": "L1\nL2", "nb": "N1\nN2"}, "maxLength": 2000},
        ],
    }


class StubFeedClient:
    def __init__(self, products, full_products=None):
        self.products = products
        if full_products is None:
            self.full_products = {
                p["identifier"]["productNo"]: _ensure_b2c_mp_true(p) for p in products
            }
        else:
            self.full_products = {
                p["identifier"]["productNo"]: p for p in full_products
            }

    def fetch_products(self, export_from, product_no=None, limit=None):
        if product_no:
            return [p for p in self.products if p["identifier"]["productNo"] == product_no]
        return self.products[:limit] if limit else self.products

    def fetch_media_base64(self, media_code):
        return "R0lGODdhAQABAIAAAP"

    def fetch_product_full(self, product_no):
        return self.full_products.get(product_no)


def _ensure_b2c_mp_true(product):
    clone = copy.deepcopy(product)
    attributes = [attr for attr in clone.get("attributes", []) if attr.get("importCode") != "b2c_mp"]
    attributes.append({"importCode": "b2c_mp", "dataType": "BOOLEAN", "value": True})
    clone["attributes"] = attributes
    return clone


class StubJetshopClient:
    def __init__(self, raise_on_get=False, dyn_failures=None, raise_on_price=False):
        self.raise_on_get = raise_on_get
        self.dyn_failures = dyn_failures or []
        self.raise_on_price = raise_on_price
        self.add_update_calls = 0
        self.dyn_save_calls = 0
        self.dyn_inputs = []
        self.delete_calls = 0
        self.delete_article_numbers = []
        self.image_uploads = []
        self.image_link_calls = 0
        self.image_link_dividers = []
        self.price_list_calls = 0
        self.price_list_inputs = []
        self.add_update_payloads = []
        self.operation_order = []

    def product_get(self, culture, article_number):
        if self.raise_on_get:
            raise RuntimeError("Jetshop read failed")
        return {}

    def dyn_get(self, article_numbers, cultures):
        if self.raise_on_get:
            raise RuntimeError("Jetshop read failed")
        return {}

    def product_add_update(self, product_data_list):
        self.operation_order.append("product_add_update")
        self.add_update_calls += 1
        self.add_update_payloads.append(product_data_list)
        return []

    def dyn_save(self, inputs):
        self.operation_order.append("dyn_save")
        self.dyn_save_calls += 1
        self.dyn_inputs.append(inputs)
        return self.dyn_failures

    def price_list_update(self, inputs):
        self.operation_order.append("price_list_update")
        self.price_list_calls += 1
        self.price_list_inputs = inputs
        if self.raise_on_price:
            raise RuntimeError("price failed")

    def product_delete(self, article_number):
        self.delete_calls += 1
        self.delete_article_numbers.append(article_number)

    def upload_image(self, base64_code, file_name, image_name):
        self.operation_order.append("upload_image")
        self.image_uploads.append((base64_code, file_name, image_name))

    def product_add_update_images(self, article_numbers, divider="_"):
        self.operation_order.append("image_link")
        self.image_link_calls += 1
        self.image_link_dividers.append(divider)
        return []


def test_sync_engine_dry_run_writes_diff(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    feed_client = StubFeedClient([build_sample_product()])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, True)

    diff_path = tmp_path / "diffs" / "Pelle-1092-10.json"
    assert diff_path.exists()
    assert report["counts"]["processed"] == 1
    assert jetshop_client.add_update_calls == 0
    assert jetshop_client.dyn_save_calls == 0
    assert jetshop_client.price_list_calls == 0
    assert state_store.read_last_run() is None


def test_sync_engine_handles_read_failure(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    feed_client = StubFeedClient([build_sample_product()])
    jetshop_client = StubJetshopClient(raise_on_get=True)
    logger = logging.getLogger("test_sync_engine_read_fail")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 1


def test_sync_engine_ignores_missing_dynamic_fields(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    feed_client = StubFeedClient([build_sample_product()])

    class Result:
        def __init__(self, key, success, message):
            self.key = key
            self.success = success
            self.message = message

    dyn_failures = [
        Result("atr_height", False, "No dynamic field, connected to product, found with key."),
        Result("atr_colour", False, "No dynamic field, connected to product, found with key."),
    ]

    jetshop_client = StubJetshopClient(dyn_failures=dyn_failures)
    logger = logging.getLogger("test_sync_engine_dyn_missing")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0


def test_sync_engine_clears_discount_on_missing(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_discount_clear")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.price_list_inputs
    for item in jetshop_client.price_list_inputs:
        assert item.get("DiscountedPriceIncVat") == item.get("PriceIncVat")
        assert item.get("UseDiscountDateSpan") is False
        assert item.get("HideProduct") is False


def test_sync_engine_clears_discount_on_zero(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append(
        {"importCode": "b2c_disc_price_mp_se", "dataType": "FLOAT", "value": 0.0}
    )
    product["attributes"].append(
        {"importCode": "b2c_disc_price_mp_no", "dataType": "FLOAT", "value": "0"}
    )
    product["attributes"].append(
        {"importCode": "b2c_disc_price_mp_b2b", "dataType": "FLOAT", "value": 0}
    )

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_discount_zero")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.price_list_inputs
    for item in jetshop_client.price_list_inputs:
        assert item.get("DiscountedPriceIncVat") == item.get("PriceIncVat")


def test_sync_engine_clears_price_on_missing_value(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"] = [
        attr for attr in product["attributes"] if attr["importCode"] != "b2c_price_no"
    ]
    product["attributes"].append({"importCode": "b2c_price_no", "dataType": "FLOAT"})

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_price_clear")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    no_item = next(
        item
        for item in jetshop_client.price_list_inputs
        if item.get("PriceListId") == "0036268d-6d49-4a21-b0a2-3c12af44fb14"
    )
    assert no_item.get("PriceIncVat") == -1


def test_sync_engine_discount_period_sets_dates(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append(
        {"importCode": "b2c_disc_price_mp_se", "dataType": "FLOAT", "value": 99.0}
    )
    product["attributes"].append(
        {
            "importCode": "b2c_disc_bo_se",
            "dataType": "DATE",
            "range": True,
            "value": ["2026-01-19T00:00:00.000+00:00", "2026-01-26T00:00:00.000+00:00"],
        }
    )

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_discount_period")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    se_item = next(
        item
        for item in jetshop_client.price_list_inputs
        if item.get("PriceListId") == "7c7dfec3-2312-4dc9-a74f-913f3da0c686"
    )
    assert se_item.get("UseDiscountDateSpan") is True
    assert isinstance(se_item.get("DiscountStartDate"), datetime)
    assert isinstance(se_item.get("DiscountEndDate"), datetime)


def test_sync_engine_clears_categories_before_update(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    feed_client = StubFeedClient([build_sample_product()])

    class CategoryJetshopClient(StubJetshopClient):
        def product_get(self, culture, article_number):
            return {"ProductInCategories": ["150", "151", "999"]}

    jetshop_client = CategoryJetshopClient()
    logger = logging.getLogger("test_sync_engine_category_reset")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.add_update_calls == 1
    update_payloads = jetshop_client.add_update_payloads[0]
    for payload in update_payloads:
        categories = payload.get("ProductInCategories", [])
        delete_entries = [
            item
            for item in categories
            if isinstance(item, dict) and item.get("ProductInCategoryState") == "DeleteConnection"
        ]
        assert delete_entries
        assert delete_entries[0]["CategoryId"] == "999"


def test_sync_engine_does_not_write_missing_mappings(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append(
        {"importCode": "unmapped_attr", "dataType": "FLOAT", "value": 12.5}
    )
    product["texts"].append(
        {"importCode": "unmapped_text", "value": {"sv": "Example"}, "maxLength": 50}
    )

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_missing_mappings")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, True)

    missing_path = tmp_path / "missing_mapped_fields.yaml"
    assert not missing_path.exists()


def test_sync_engine_auto_maps_dynamic_fields(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append(
        {"importCode": "atr_dia", "dataType": "FLOAT", "value": 55.0}
    )

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_auto_dyn")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.dyn_inputs
    posted_keys = {item["Key"] for item in jetshop_client.dyn_inputs[0]}
    assert "atr_dia" in posted_keys


def test_sync_engine_clears_dynamic_field_when_value_removed(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append({"importCode": "atr_dia", "dataType": "FLOAT"})

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_clear_dyn")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.dyn_inputs
    dia_items = [item for item in jetshop_client.dyn_inputs[0] if item["Key"] == "atr_dia"]
    assert dia_items
    for loc in dia_items[0].get("ItemValues", []):
        assert loc.get("Value") == ""


def test_sync_engine_uploads_images(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["media"] = [
        {
            "action": "CREATE",
            "mediaCode": "7785",
            "mediaType": "IMAGE",
            "fileName": "Pelle-3447-10.jpg",
            "sortNo": 3,
        }
    ]

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_images")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.image_uploads
    assert jetshop_client.image_uploads[0][1] == "Pelle-1092-10_3.jpg"
    assert jetshop_client.image_uploads[0][2] == "Pelle-1092-10_3.jpg"
    assert jetshop_client.image_link_calls == 1
    assert jetshop_client.image_link_dividers == ["_"]


def test_sync_engine_prefers_feed_sorting_field_for_image_name(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["media"] = [
        {
            "action": "CREATE",
            "mediaCode": "7785",
            "mediaType": "IMAGE",
            "fileName": "Pelle-3447-99.jpg",
            "sortNo": 9,
            "sorting": 2,
        }
    ]

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_images_sorting")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.image_uploads[0][1] == "Pelle-1092-10_2.jpg"


def test_sync_engine_uses_full_product_for_single_item_mapping_and_images(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    partial_product = {
        "identifier": {"productNo": "Pelle-1092-10"},
        "attributes": [{"importCode": "monitor_disp", "dataType": "FLOAT", "value": 10.0}],
        "texts": [{"importCode": "name_1", "value": {"sv": "Nigella"}}],
        "media": [{"mediaCode": "7785", "mediaType": "IMAGE", "fileName": "changed.jpg", "sortNo": 1}],
    }
    full_product = build_sample_product()
    full_product["media"] = [
        {
            "mediaCode": "7786",
            "mediaType": "IMAGE",
            "fileName": "snitt-1092-10c.jpg",
            "sortNo": 2,
        },
        {
            "mediaCode": "7785",
            "mediaType": "IMAGE",
            "fileName": "1092-10.jpg",
            "sortNo": 1,
        },
    ]

    feed_client = StubFeedClient([partial_product], full_products=[_ensure_b2c_mp_true(full_product)])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_full_product_mapping")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    update_payload = jetshop_client.add_update_payloads[0][0]
    assert update_payload["ProductDescription"] == "L1<br>L2"
    assert update_payload["EanCode"] == "123"
    assert update_payload["ProductInCategories"]
    assert jetshop_client.price_list_inputs
    assert [item[1] for item in jetshop_client.image_uploads] == [
        "Pelle-1092-10_1.jpg",
        "Pelle-1092-10_2.jpg",
    ]


def test_sync_engine_stops_image_sync_when_price_list_update_fails(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["media"] = [
        {
            "action": "CREATE",
            "mediaCode": "7785",
            "mediaType": "IMAGE",
            "fileName": "Pelle-3447-10.jpg",
            "sortNo": 3,
        }
    ]

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient(raise_on_price=True)
    logger = logging.getLogger("test_sync_engine_images_before_price_failure")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 1
    assert jetshop_client.image_uploads == []
    assert jetshop_client.image_link_calls == 0
    assert jetshop_client.operation_order[-1] == "price_list_update"


def test_sync_engine_single_item_falls_back_to_full_product_when_no_changes(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    full_product = _ensure_b2c_mp_true(build_sample_product())
    feed_client = StubFeedClient([], full_products=[full_product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_single_item_full_fallback")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["processed"] == 1
    assert report["counts"]["failed"] == 0
    assert jetshop_client.add_update_calls == 1


def test_sync_engine_reloads_images_when_feed_image_deleted(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    partial_product = build_sample_product()
    partial_product["media"] = [
        {
            "action": "DELETE",
            "mediaCode": "7785",
            "mediaType": "IMAGE",
            "fileName": "old.jpg",
            "sortNo": 1,
        }
    ]
    full_product = build_sample_product()
    full_product["media"] = []

    feed_client = StubFeedClient([partial_product], full_products=[_ensure_b2c_mp_true(full_product)])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_image_delete")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", None, None, False)

    assert report["counts"]["failed"] == 0
    assert jetshop_client.image_uploads == []
    assert jetshop_client.image_link_calls == 1
    assert jetshop_client.image_link_dividers == ["_"]


def test_sync_engine_preserves_delivery_date_when_feed_value_missing(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"] = [
        attr for attr in product["attributes"] if attr["importCode"] != "monitor_deliverydate"
    ]
    product["attributes"].append({"importCode": "monitor_deliverydate", "dataType": "UNI_TEXT"})

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_preserve_delivery_date")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    payload = jetshop_client.add_update_payloads[0][0]
    assert "DeliveryDate" not in payload.get("StockData", {})


def test_sync_engine_missing_show_flag_hides_product(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"] = [
        attr for attr in product["attributes"] if attr["importCode"] != "se_show_mp"
    ]
    product["attributes"].append(
        {"importCode": "se_show_mp", "dataType": "BOOLEAN"}
    )

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_hide_missing")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    se_item = next(
        item
        for item in jetshop_client.price_list_inputs
        if item.get("PriceListId") == "7c7dfec3-2312-4dc9-a74f-913f3da0c686"
    )
    assert se_item.get("HideProduct") is True


def test_sync_engine_missing_boolean_dynamic_field_sets_true(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["attributes"].append({"importCode": "b2c_mp", "dataType": "BOOLEAN"})

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_missing_boolean_dyn")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["failed"] == 0
    b2c_items = [item for item in jetshop_client.dyn_inputs[0] if item["Key"] == "b2c_mp"]
    assert b2c_items
    for loc in b2c_items[0].get("ItemValues", []):
        assert loc.get("Value") == "true"


def test_sync_engine_skips_when_b2c_mp_missing_in_full(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    full_product = build_sample_product()
    full_product["attributes"] = [
        attr for attr in full_product["attributes"] if attr["importCode"] != "b2c_mp"
    ]
    full_product["attributes"].append({"importCode": "b2c_mp", "dataType": "BOOLEAN"})

    feed_client = StubFeedClient([product], full_products=[full_product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_skip_b2c_mp")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["skipped"] == 1
    assert jetshop_client.add_update_calls == 0
    assert jetshop_client.dyn_save_calls == 0
    assert jetshop_client.price_list_calls == 0


def test_sync_engine_deletes_when_feed_marked_deleted(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["productHead"] = {"deleted": True}

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_delete_flag")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["deleted"] == 1
    assert jetshop_client.delete_calls == 1
    assert jetshop_client.delete_article_numbers == ["Pelle-1092-10"]


def test_sync_engine_deletes_when_top_level_deleted(tmp_path, monkeypatch):
    mapping_path = Path(__file__).resolve().parents[1] / "mappings" / "mapping.yaml"
    mapping = load_mapping(mapping_path)

    product = build_sample_product()
    product["deleted"] = "true"

    feed_client = StubFeedClient([product])
    jetshop_client = StubJetshopClient()
    logger = logging.getLogger("test_sync_engine_delete_top_level")
    logger.addHandler(logging.NullHandler())
    state_store = StateStore(tmp_path / "state" / "last_run.json")

    monkeypatch.chdir(tmp_path)

    engine = SyncEngine(feed_client, jetshop_client, mapping, logger, state_store)
    report = engine.sync("2025-01-01T00:00:00Z", "Pelle-1092-10", None, False)

    assert report["counts"]["deleted"] == 1
    assert jetshop_client.delete_calls == 1
