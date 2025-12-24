"""字段路径解析模块测试"""

import pytest

from dtflow.utils.field_path import (
    get_field,
    get_field_with_spec,
    parse_field_spec,
)


class TestParseFieldSpec:
    """parse_field_spec 函数测试"""

    def test_simple_path(self):
        assert parse_field_spec("meta.source") == ("meta.source", "first")

    def test_path_with_mode(self):
        assert parse_field_spec("messages[*].role:join") == ("messages[*].role", "join")
        assert parse_field_spec("messages[*].role:unique") == ("messages[*].role", "unique")
        assert parse_field_spec("messages[*].role:first") == ("messages[*].role", "first")

    def test_invalid_mode_treated_as_path(self):
        # 无效的模式被当作路径的一部分
        assert parse_field_spec("field:invalid") == ("field:invalid", "first")


class TestGetFieldNested:
    """嵌套字段访问测试"""

    def test_single_level(self):
        data = {"name": "test", "value": 123}
        assert get_field(data, "name") == "test"
        assert get_field(data, "value") == 123

    def test_two_levels(self):
        data = {"meta": {"source": "wiki", "lang": "zh"}}
        assert get_field(data, "meta.source") == "wiki"
        assert get_field(data, "meta.lang") == "zh"

    def test_three_levels(self):
        data = {"a": {"b": {"c": "deep"}}}
        assert get_field(data, "a.b.c") == "deep"

    def test_missing_field(self):
        data = {"meta": {"source": "wiki"}}
        assert get_field(data, "meta.missing") is None
        assert get_field(data, "meta.missing", default="N/A") == "N/A"
        assert get_field(data, "nonexistent.field") is None


class TestGetFieldArrayIndex:
    """数组索引访问测试"""

    def test_positive_index(self):
        data = {"items": ["a", "b", "c"]}
        assert get_field(data, "items[0]") == "a"
        assert get_field(data, "items[1]") == "b"
        assert get_field(data, "items[2]") == "c"

    def test_negative_index(self):
        data = {"items": ["a", "b", "c"]}
        assert get_field(data, "items[-1]") == "c"
        assert get_field(data, "items[-2]") == "b"

    def test_index_with_nested_field(self):
        data = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]
        }
        assert get_field(data, "messages[0].role") == "system"
        assert get_field(data, "messages[1].role") == "user"
        assert get_field(data, "messages[-1].role") == "assistant"
        assert get_field(data, "messages[-1].content") == "Hi there"

    def test_index_out_of_range(self):
        data = {"items": ["a", "b"]}
        assert get_field(data, "items[10]") is None
        assert get_field(data, "items[10]", default="N/A") == "N/A"


class TestGetFieldArrayLength:
    """数组长度测试"""

    def test_array_length(self):
        data = {"items": [1, 2, 3, 4, 5]}
        assert get_field(data, "items.#") == 5

    def test_nested_array_length(self):
        data = {"messages": [{"role": "user"}, {"role": "assistant"}]}
        assert get_field(data, "messages.#") == 2

    def test_empty_array_length(self):
        data = {"items": []}
        assert get_field(data, "items.#") == 0

    def test_string_length(self):
        data = {"text": "hello"}
        assert get_field(data, "text.#") == 5


class TestGetFieldExpand:
    """数组展开测试"""

    @pytest.fixture
    def messages_data(self):
        return {
            "messages": [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "How are you?"},
            ]
        }

    def test_expand_first_mode(self, messages_data):
        # 默认 first 模式
        assert get_field(messages_data, "messages[*].role") == "system"
        assert get_field(messages_data, "messages[*].role", mode="first") == "system"

    def test_expand_join_mode(self, messages_data):
        result = get_field(messages_data, "messages[*].role", mode="join")
        assert result == "system|user|assistant|user"

    def test_expand_unique_mode(self, messages_data):
        result = get_field(messages_data, "messages[*].role", mode="unique")
        # unique 模式会去重并排序
        assert result == "assistant|system|user"

    def test_expand_with_nested_path(self):
        data = {
            "conversations": [
                {"meta": {"type": "qa"}},
                {"meta": {"type": "chat"}},
                {"meta": {"type": "qa"}},
            ]
        }
        assert get_field(data, "conversations[*].meta.type", mode="unique") == "chat|qa"

    def test_expand_empty_array(self):
        data = {"messages": []}
        assert get_field(data, "messages[*].role") is None


class TestGetFieldWithSpec:
    """get_field_with_spec 函数测试"""

    def test_simple_spec(self):
        data = {"meta": {"source": "wiki"}}
        assert get_field_with_spec(data, "meta.source") == "wiki"

    def test_spec_with_mode(self):
        data = {"tags": [{"name": "a"}, {"name": "b"}, {"name": "a"}]}
        assert get_field_with_spec(data, "tags[*].name:join") == "a|b|a"
        assert get_field_with_spec(data, "tags[*].name:unique") == "a|b"


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_path(self):
        data = {"key": "value"}
        assert get_field(data, "") is None

    def test_none_data(self):
        assert get_field(None, "field") is None  # type: ignore

    def test_non_dict_data(self):
        assert get_field([1, 2, 3], "field") is None  # type: ignore

    def test_chinese_field_names(self):
        data = {"元数据": {"来源": "维基百科"}}
        assert get_field(data, "元数据.来源") == "维基百科"

    def test_complex_nested_structure(self):
        data = {
            "level1": {
                "level2": [
                    {"level3": {"value": "found"}},
                    {"level3": {"value": "also found"}},
                ]
            }
        }
        assert get_field(data, "level1.level2[0].level3.value") == "found"
        assert get_field(data, "level1.level2[-1].level3.value") == "also found"
        assert get_field(data, "level1.level2[*].level3.value", mode="join") == "found|also found"
