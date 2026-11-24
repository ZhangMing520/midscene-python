"""Port of upstream packages/shared/tests/unit-test/node-cache.test.ts plus
coverage for the DOM-shim helpers in extractor/util.ts."""

from types import SimpleNamespace

import pytest

from midscene.shared.extractor import util


class FakeStyle(dict):
    def getPropertyValue(self, name):
        return self.get(name, "")


class FakeRect:
    def __init__(self, left=0, top=0, width=0, height=0):
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.right = left + width
        self.bottom = top + height
        self.x = left
        self.y = top


class HTMLElement:
    pass


class FakeElement(HTMLElement):
    def __init__(
        self,
        node_name="DIV",
        attributes=None,
        rect=None,
        style=None,
        pseudo_styles=None,
        tag_name=None,
        parent=None,
    ):
        self.nodeType = util.ELEMENT_NODE
        self.nodeName = node_name
        self.tagName = tag_name or node_name.upper()
        self.textContent = ""
        self.attributes = attributes or {}
        self.style = FakeStyle(style or {})
        self.pseudo_styles = pseudo_styles or {}
        self.parentElement = parent
        self._rect = rect or FakeRect()
        self.childNodes = []

    def getBoundingClientRect(self):
        return self._rect

    def contains(self, other):
        return False


class FakeTextNode:
    def __init__(self, text):
        self.nodeType = util.TEXT_NODE
        self.nodeName = "#text"
        self.textContent = text


class FakeRange:
    def __init__(self, node):
        self._node = node

    def selectNodeContents(self, node):
        self._node = node

    def getBoundingClientRect(self):
        return self._node.getBoundingClientRect()


class FakeDocument:
    def __init__(self, body=None):
        self.body = body
        self.documentElement = SimpleNamespace(clientWidth=1000, clientHeight=800)

    def elementFromPoint(self, x, y):
        return None

    def createRange(self):
        return FakeRange(SimpleNamespace())


class FakeWindow:
    HTMLElement = HTMLElement

    def __init__(self, document=None, width=1000, height=800):
        self.innerWidth = width
        self.innerHeight = height
        self.document = document or FakeDocument()

    def getComputedStyle(self, element, pseudo=None):
        if pseudo is not None:
            return element.pseudo_styles.get(pseudo, FakeStyle())
        return element.style


@pytest.fixture
def window():
    document = FakeDocument()
    current_window = FakeWindow(document)
    document.defaultView = current_window
    return current_window


class TestNodeCache:
    # upstream: beforeEach sets global.window = {}
    def setup_method(self):
        util.window = {}
        util._node_hash_cache = None

    def teardown_method(self):
        util.window = None
        util._node_hash_cache = None

    def test_should_initialize_an_empty_map_on_window(self):
        """should initialize an empty Map on window"""
        util.set_node_hash_cache_list_on_window()
        assert util._node_hash_cache == {}

    def test_should_reset_existing_cache_when_called_again(self):
        """should reset existing cache when called again"""
        util.set_node_hash_cache_list_on_window()
        util.set_node_to_cache_list({"nodeName": "div"}, "x")
        util.set_node_hash_cache_list_on_window()
        assert len(util._node_hash_cache) == 0

    def test_should_cache_a_node_and_retrieve_it_by_id(self):
        """should cache a node and retrieve it by id"""
        util.set_node_hash_cache_list_on_window()
        node = {"nodeName": "div"}
        util.set_node_to_cache_list(node, "abc123")
        assert util.get_node_from_cache_list("abc123") is node

    def test_should_return_undefined_for_unknown_id(self):
        """should return undefined for unknown id"""
        util.set_node_hash_cache_list_on_window()
        assert util.get_node_from_cache_list("nonexistent") is None

    def test_should_not_duplicate_entries_with_same_id(self):
        """should not duplicate entries with same id"""
        util.set_node_hash_cache_list_on_window()
        node1 = {"nodeName": "span"}
        node2 = {"nodeName": "div"}
        util.set_node_to_cache_list(node1, "dup-id")
        util.set_node_to_cache_list(node2, "dup-id")
        assert util.get_node_from_cache_list("dup-id") is node1
        assert util._node_hash_cache["dup-id"] is node1

    def test_should_not_cache_when_cache_is_not_initialized(self):
        """should not cache when cache is not initialized"""
        util.set_node_to_cache_list({"nodeName": "p"}, "no-init")
        assert util.get_node_from_cache_list("no-init") is None

    def test_should_auto_initialize_cache_via_midscene_generate_hash(self):
        """should auto-initialize cache via midsceneGenerateHash"""
        mock_node = {"nodeName": "p"}
        util.midscene_generate_hash(
            mock_node, "content", {"left": 0, "top": 0, "width": 10, "height": 10}
        )
        assert (
            util.get_node_from_cache_list(
                util.midscene_generate_hash(
                    None,
                    "content",
                    {"left": 0, "top": 0, "width": 10, "height": 10},
                )
            )
            is mock_node
        )

    def test_should_evict_oldest_entry_when_cache_exceeds_max_size(self):
        """should evict oldest entry when cache exceeds max size"""
        util.set_node_hash_cache_list_on_window()
        for index in range(util.NODE_CACHE_MAX_SIZE + 1):
            util.set_node_to_cache_list({"nodeName": f"node-{index}"}, f"id-{index}")
        assert util.get_node_from_cache_list("id-0") is None
        assert util.get_node_from_cache_list("id-2000") is not None

    def test_should_cache_the_node_when_generating_a_hash(self):
        """should cache the node when generating a hash"""
        mock_node = {"nodeName": "button"}
        hash_value = util.midscene_generate_hash(
            mock_node,
            "click me",
            {"left": 10, "top": 20, "width": 100, "height": 40},
        )
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0
        assert util.get_node_from_cache_list(hash_value) is mock_node

    def test_should_not_crash_when_node_is_null(self):
        """should not crash when node is null"""
        hash_value = util.midscene_generate_hash(
            None, "text", {"left": 0, "top": 0, "width": 50, "height": 50}
        )
        assert isinstance(hash_value, str)

    def test_should_produce_same_hash_for_same_content_rect(self):
        """should produce same hash for same content+rect"""
        rect = {"left": 1, "top": 2, "width": 3, "height": 4}
        assert util.midscene_generate_hash(None, "same", rect) == (
            util.midscene_generate_hash(None, "same", rect)
        )

    def test_should_produce_different_hashes_for_different_content(self):
        """should produce different hashes for different content"""
        rect = {"left": 1, "top": 2, "width": 3, "height": 4}
        assert util.midscene_generate_hash(None, "aaa", rect) != (
            util.midscene_generate_hash(None, "bbb", rect)
        )


class TestDomHelpers:
    def test_get_rect_applies_computed_zoom(self, window):
        element = FakeElement(rect=FakeRect(10, 20, 100, 40), style={"zoom": "2"})
        rect = util.get_rect(element, 1, window)
        assert rect["width"] == 200
        assert rect["height"] == 80
        assert rect["left"] == 20
        assert rect["zoom"] == 2

    def test_get_rect_uses_range_for_text_nodes(self, window):
        text = FakeTextNode("hello")
        text.getBoundingClientRect = lambda: FakeRect(1, 2, 3, 4)
        rect = util.get_rect(text, 1, window)
        assert rect["left"] == 1
        assert rect["height"] == 4

    def test_get_pseudo_element_content_strips_quotes_and_none(self, window):
        element = FakeElement(
            pseudo_styles={
                "::before": FakeStyle({"content": '"before"'}),
                "::after": FakeStyle({"content": "none"}),
            }
        )
        assert util.get_pseudo_element_content(element, window) == {
            "before": "before",
            "after": "",
        }
        assert util.get_pseudo_element_content(object(), window) == {
            "before": "",
            "after": "",
        }

    def test_has_overflow_y(self, window):
        assert util.has_overflow_y(FakeElement(style={"overflowY": "auto"}), window)
        assert util.has_overflow_y(FakeElement(style={"overflowY": "hidden"}), window)
        assert not util.has_overflow_y(
            FakeElement(style={"overflowY": "visible"}), window
        )

    def test_valid_text_node_content(self):
        assert util.valid_text_node_content(FakeTextNode("  hello  ")) == "hello"
        assert util.valid_text_node_content(FakeTextNode("   ")) is False
        assert util.valid_text_node_content(None) is False
        assert util.valid_text_node_content(SimpleNamespace(nodeType=8)) is False
        element = FakeElement()
        element.textContent = "text"
        assert util.valid_text_node_content(element) == "text"

    def test_get_node_attributes_trims_values(self, window):
        element = FakeElement(
            attributes={
                "class": "a b",
                "data-src": "data:image/png;base64,abc",
                "title": "x" * (util.MAX_VALUE_LENGTH + 1),
            }
        )
        attributes = util.get_node_attributes(element, window)
        assert attributes["class"] == ".a.b"
        assert attributes["data-src"] == "image"
        assert attributes["title"] == f"{'x' * util.MAX_VALUE_LENGTH}..."
        assert util.get_node_attributes(object(), window) == {}

    def test_element_rect_rejects_hidden_and_sizeless_elements(self, window):
        assert util.element_rect(None, window, window.document) is False
        assert (
            util.element_rect(
                FakeElement(style={"display": "none"}), window, window.document
            )
            is False
        )
        assert (
            util.element_rect(
                FakeElement(rect=FakeRect(0, 0, 0, 0)), window, window.document
            )
            is False
        )

    def test_element_rect_returns_rounded_visible_rect(self, window):
        element = FakeElement(rect=FakeRect(10.4, 20.6, 100.2, 40.8))
        rect = util.element_rect(element, window, window.document)
        assert rect == {
            "left": 10,
            "top": 21,
            "width": 100,
            "height": 41,
            "zoom": 1,
            "isVisible": True,
        }

    def test_element_rect_returns_false_when_covered(self, window):
        element = FakeElement(rect=FakeRect(10, 20, 100, 40))
        cover = FakeElement(rect=FakeRect(0, 0, 500, 500))
        window.document.elementFromPoint = lambda x, y: cover
        assert util.element_rect(element, window, window.document) is False

    def test_generate_id(self):
        assert util.generate_id(12) == "12"
        assert util.generate_id(1.0) == "1"
        assert util.generate_id(True) == "true"

    def test_get_top_document(self, monkeypatch):
        body = FakeElement(rect=FakeRect(0, 0, 10, 10))
        fake_document = FakeDocument(body=body)
        monkeypatch.setattr(util, "document", fake_document)
        assert util.get_top_document() is body
        monkeypatch.setattr(util, "document", None)
        assert util.get_top_document() is None

    def test_window_setters_attach_helpers(self, monkeypatch):
        fake_window = SimpleNamespace()
        monkeypatch.setattr(util, "window", fake_window)
        util.set_generate_hash_on_window()
        util.set_midscene_visible_rect_on_window()
        assert fake_window.midsceneGenerateHash is util.midscene_generate_hash
        assert fake_window.midsceneVisibleRect is util.element_rect

        def extractor(*args, **kwargs):
            return args

        monkeypatch.setattr(
            util, "extract_text_with_position", extractor, raising=False
        )
        util.set_extract_text_with_position_on_window()
        assert fake_window.extractTextWithPosition is extractor
