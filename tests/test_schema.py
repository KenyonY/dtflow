"""
Schema 验证模块测试
"""

import pytest

from dtflow.schema import (
    Field,
    Schema,
    ValidationError,
    ValidationResult,
    alpaca_schema,
    dpo_schema,
    openai_chat_schema,
    sharegpt_schema,
    validate_data,
)
from dtflow import DataTransformer


class TestField:
    """Field 类测试"""

    def test_type_validation_str(self):
        """测试字符串类型验证"""
        field = Field(type="str")
        assert field.validate("hello", "test") == []
        errors = field.validate(123, "test")
        assert len(errors) == 1
        assert "类型错误" in errors[0].message

    def test_type_validation_int(self):
        """测试整数类型验证"""
        field = Field(type="int")
        assert field.validate(42, "test") == []
        errors = field.validate("42", "test")
        assert len(errors) == 1

    def test_type_validation_float(self):
        """测试浮点数类型验证（也接受 int）"""
        field = Field(type="float")
        assert field.validate(3.14, "test") == []
        assert field.validate(42, "test") == []  # int 也可以
        errors = field.validate("3.14", "test")
        assert len(errors) == 1

    def test_type_validation_bool(self):
        """测试布尔类型验证"""
        field = Field(type="bool")
        assert field.validate(True, "test") == []
        assert field.validate(False, "test") == []
        errors = field.validate(1, "test")
        assert len(errors) == 1

    def test_type_validation_list(self):
        """测试列表类型验证"""
        field = Field(type="list")
        assert field.validate([1, 2, 3], "test") == []
        errors = field.validate("not a list", "test")
        assert len(errors) == 1

    def test_type_validation_dict(self):
        """测试字典类型验证"""
        field = Field(type="dict")
        assert field.validate({"a": 1}, "test") == []
        errors = field.validate([1, 2], "test")
        assert len(errors) == 1

    def test_required_field(self):
        """测试必填字段"""
        field = Field(required=True)
        errors = field.validate(None, "test")
        assert len(errors) == 1
        assert "不能为 None" in errors[0].message

    def test_nullable_field(self):
        """测试可空字段"""
        field = Field(nullable=True)
        assert field.validate(None, "test") == []

    def test_min_max_value(self):
        """测试数值范围"""
        field = Field(type="float", min=0, max=1)
        assert field.validate(0.5, "test") == []
        assert field.validate(0, "test") == []
        assert field.validate(1, "test") == []

        errors = field.validate(-0.1, "test")
        assert len(errors) == 1
        assert "不能小于" in errors[0].message

        errors = field.validate(1.1, "test")
        assert len(errors) == 1
        assert "不能大于" in errors[0].message

    def test_min_max_length(self):
        """测试长度范围"""
        field = Field(type="str", min_length=2, max_length=5)
        assert field.validate("abc", "test") == []
        assert field.validate("ab", "test") == []
        assert field.validate("abcde", "test") == []

        errors = field.validate("a", "test")
        assert len(errors) == 1
        assert "长度不能小于" in errors[0].message

        errors = field.validate("abcdef", "test")
        assert len(errors) == 1
        assert "长度不能大于" in errors[0].message

    def test_list_length(self):
        """测试列表长度"""
        field = Field(type="list", min_length=1, max_length=3)
        assert field.validate([1], "test") == []
        assert field.validate([1, 2, 3], "test") == []

        errors = field.validate([], "test")
        assert len(errors) == 1

        errors = field.validate([1, 2, 3, 4], "test")
        assert len(errors) == 1

    def test_choices(self):
        """测试选项验证"""
        field = Field(type="str", choices=["user", "assistant", "system"])
        assert field.validate("user", "test") == []
        assert field.validate("assistant", "test") == []

        errors = field.validate("admin", "test")
        assert len(errors) == 1
        assert "必须是" in errors[0].message

    def test_pattern(self):
        """测试正则表达式"""
        field = Field(type="str", pattern=r"^\d{4}-\d{2}-\d{2}$")
        assert field.validate("2024-01-08", "test") == []

        errors = field.validate("2024/01/08", "test")
        assert len(errors) == 1
        assert "不匹配模式" in errors[0].message

    def test_custom_validation(self):
        """测试自定义验证函数"""
        # 返回 bool
        field = Field(custom=lambda x: x > 0)
        assert field.validate(1, "test") == []
        errors = field.validate(-1, "test")
        assert len(errors) == 1

        # 返回错误信息
        field = Field(custom=lambda x: "必须是偶数" if x % 2 != 0 else True)
        assert field.validate(2, "test") == []
        errors = field.validate(3, "test")
        assert len(errors) == 1
        assert "必须是偶数" in errors[0].message

    def test_type_any(self):
        """测试 any 类型"""
        field = Field(type="any")
        assert field.validate("string", "test") == []
        assert field.validate(123, "test") == []
        assert field.validate([1, 2, 3], "test") == []
        assert field.validate({"a": 1}, "test") == []


class TestSchema:
    """Schema 类测试"""

    def test_simple_schema(self):
        """测试简单 Schema"""
        schema = Schema(
            {
                "name": Field(type="str", required=True),
                "age": Field(type="int", min=0),
            }
        )

        result = schema.validate({"name": "Alice", "age": 25})
        assert result.valid

        result = schema.validate({"name": "Bob"})
        assert result.valid  # age 没有 required=True

        result = schema.validate({"age": 25})
        assert not result.valid
        assert any("name" in e.path for e in result.errors)

    def test_nested_field_path(self):
        """测试嵌套字段路径"""
        schema = Schema(
            {
                "meta.source": Field(type="str", required=True),
                "meta.id": Field(type="int"),
            }
        )

        result = schema.validate({"meta": {"source": "wiki", "id": 123}})
        assert result.valid

        result = schema.validate({"meta": {"id": 123}})
        assert not result.valid

    def test_array_index_path(self):
        """测试数组索引路径"""
        schema = Schema(
            {
                "items[0].name": Field(type="str"),
                "items[-1].value": Field(type="int"),
            }
        )

        result = schema.validate(
            {"items": [{"name": "first", "value": 1}, {"name": "last", "value": 2}]}
        )
        assert result.valid

    def test_expand_field_path(self):
        """测试展开字段路径 [*]"""
        schema = Schema(
            {
                "messages": Field(type="list", required=True, min_length=1),
                "messages[*].role": Field(
                    type="str", choices=["user", "assistant", "system"]
                ),
                "messages[*].content": Field(type="str", min_length=1),
            }
        )

        # 有效数据
        result = schema.validate(
            {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ]
            }
        )
        assert result.valid

        # 无效角色
        result = schema.validate(
            {"messages": [{"role": "admin", "content": "hello"}]}
        )
        assert not result.valid
        assert any("role" in e.path for e in result.errors)

        # 空内容
        result = schema.validate({"messages": [{"role": "user", "content": ""}]})
        assert not result.valid
        assert any("content" in e.path for e in result.errors)

    def test_missing_required_field(self):
        """测试缺失必填字段"""
        schema = Schema({"required_field": Field(type="str", required=True)})

        result = schema.validate({})
        assert not result.valid
        assert any("必填字段缺失" in e.message for e in result.errors)

    def test_field_exists_but_none(self):
        """测试字段存在但值为 None"""
        schema = Schema({"field": Field(type="str", required=True)})

        result = schema.validate({"field": None})
        assert not result.valid
        assert any("不能为 None" in e.message for e in result.errors)

    def test_nullable_field_in_schema(self):
        """测试 Schema 中的可空字段"""
        schema = Schema(
            {"score": Field(type="float", min=0, max=1, nullable=True, required=False)}
        )

        result = schema.validate({"score": None})
        assert result.valid

        result = schema.validate({})
        assert result.valid

    def test_validate_batch(self):
        """测试批量验证"""
        schema = Schema({"value": Field(type="int", min=0)})

        data = [
            {"value": 1},
            {"value": -1},  # 错误
            {"value": 2},
            {"value": -2},  # 错误
        ]

        failed = schema.validate_batch(data)
        assert len(failed) == 2
        assert failed[0][0] == 1  # 第 1 条
        assert failed[1][0] == 3  # 第 3 条

    def test_validation_result_bool(self):
        """测试 ValidationResult 的布尔转换"""
        result = ValidationResult(valid=True)
        assert result
        assert bool(result) is True

        result = ValidationResult(valid=False, errors=[ValidationError("test", "error")])
        assert not result
        assert bool(result) is False


class TestPresetSchemas:
    """预设 Schema 模板测试"""

    def test_openai_chat_schema(self):
        """测试 OpenAI Chat Schema"""
        schema = openai_chat_schema()

        # 有效数据
        result = schema.validate(
            {"messages": [{"role": "user", "content": "hello"}]}
        )
        assert result.valid

        # 空消息
        result = schema.validate({"messages": []})
        assert not result.valid

        # 无效角色
        result = schema.validate(
            {"messages": [{"role": "admin", "content": "hello"}]}
        )
        assert not result.valid

    def test_openai_chat_schema_custom_roles(self):
        """测试自定义角色"""
        schema = openai_chat_schema(roles=["human", "ai"])

        result = schema.validate(
            {"messages": [{"role": "human", "content": "hello"}]}
        )
        assert result.valid

        result = schema.validate(
            {"messages": [{"role": "user", "content": "hello"}]}
        )
        assert not result.valid

    def test_alpaca_schema(self):
        """测试 Alpaca Schema"""
        schema = alpaca_schema()

        result = schema.validate(
            {"instruction": "Write a poem", "output": "Roses are red..."}
        )
        assert result.valid

        result = schema.validate(
            {
                "instruction": "Translate",
                "input": "Hello",
                "output": "你好",
            }
        )
        assert result.valid

        # 缺少 instruction
        result = schema.validate({"output": "something"})
        assert not result.valid

    def test_alpaca_schema_require_input(self):
        """测试 Alpaca Schema 必填 input"""
        schema = alpaca_schema(require_input=True)

        result = schema.validate(
            {"instruction": "Write a poem", "output": "Roses are red..."}
        )
        assert not result.valid

    def test_dpo_schema(self):
        """测试 DPO Schema"""
        schema = dpo_schema()

        result = schema.validate(
            {"prompt": "What is 2+2?", "chosen": "4", "rejected": "5"}
        )
        assert result.valid

        # 缺少 rejected
        result = schema.validate({"prompt": "What is 2+2?", "chosen": "4"})
        assert not result.valid

    def test_sharegpt_schema(self):
        """测试 ShareGPT Schema"""
        schema = sharegpt_schema()

        result = schema.validate(
            {
                "conversations": [
                    {"from": "human", "value": "hello"},
                    {"from": "gpt", "value": "hi"},
                ]
            }
        )
        assert result.valid

        # 无效角色
        result = schema.validate(
            {"conversations": [{"from": "user", "value": "hello"}]}
        )
        assert not result.valid


class TestDataTransformerIntegration:
    """DataTransformer 集成测试"""

    def test_validate_schema_skip(self):
        """测试 validate_schema 的 skip 模式"""
        schema = Schema({"value": Field(type="int", min=0)})
        dt = DataTransformer(
            [{"value": 1}, {"value": -1}, {"value": 2}, {"value": -2}]
        )

        errors = dt.validate_schema(schema, on_error="skip")
        assert len(errors) == 2

    def test_validate_schema_raise(self):
        """测试 validate_schema 的 raise 模式"""
        schema = Schema({"value": Field(type="int", min=0)})
        dt = DataTransformer([{"value": 1}, {"value": -1}])

        with pytest.raises(ValueError) as exc_info:
            dt.validate_schema(schema, on_error="raise")
        assert "第 1 行验证失败" in str(exc_info.value)

    def test_validate_schema_filter(self):
        """测试 validate_schema 的 filter 模式"""
        schema = Schema({"value": Field(type="int", min=0)})
        dt = DataTransformer(
            [{"value": 1}, {"value": -1}, {"value": 2}, {"value": -2}]
        )

        valid_dt = dt.validate_schema(schema, on_error="filter")
        assert len(valid_dt) == 2
        assert valid_dt[0]["value"] == 1
        assert valid_dt[1]["value"] == 2

    def test_validate_schema_all_valid(self):
        """测试所有数据都有效的情况"""
        schema = Schema({"name": Field(type="str")})
        dt = DataTransformer([{"name": "Alice"}, {"name": "Bob"}])

        errors = dt.validate_schema(schema, on_error="skip")
        assert len(errors) == 0

    def test_validate_schema_empty_data(self):
        """测试空数据"""
        schema = Schema({"value": Field(type="int")})
        dt = DataTransformer([])

        errors = dt.validate_schema(schema, on_error="skip")
        assert len(errors) == 0


class TestValidateDataFunction:
    """validate_data 便捷函数测试"""

    def test_validate_single_item(self):
        """测试验证单条数据"""
        schema = Schema({"value": Field(type="int", min=0)})

        result = validate_data({"value": 1}, schema)
        assert result.valid

        result = validate_data({"value": -1}, schema)
        assert not result.valid

    def test_validate_list(self):
        """测试验证数据列表"""
        schema = Schema({"value": Field(type="int", min=0)})

        result = validate_data([{"value": 1}, {"value": 2}], schema)
        assert result.valid

        result = validate_data([{"value": 1}, {"value": -1}], schema)
        assert not result.valid
        assert any("[1]" in e.path for e in result.errors)


class TestEdgeCases:
    """边界情况测试"""

    def test_deeply_nested_path(self):
        """测试深层嵌套路径"""
        schema = Schema(
            {"a.b.c.d": Field(type="int")}
        )

        result = schema.validate({"a": {"b": {"c": {"d": 42}}}})
        assert result.valid

    def test_expand_with_empty_array(self):
        """测试展开空数组"""
        schema = Schema(
            {
                "items": Field(type="list", min_length=0),
                "items[*].value": Field(type="int"),
            }
        )

        result = schema.validate({"items": []})
        assert result.valid

    def test_multiple_errors_same_item(self):
        """测试同一条数据多个错误"""
        schema = Schema(
            {
                "name": Field(type="str", required=True),
                "age": Field(type="int", min=0, required=True),
            }
        )

        result = schema.validate({})
        assert not result.valid
        assert len(result.errors) == 2

    def test_non_dict_data(self):
        """测试非字典数据"""
        schema = Schema({"value": Field(type="int")})

        result = schema.validate("not a dict")  # type: ignore
        assert not result.valid
        assert any("必须是字典类型" in e.message for e in result.errors)

    def test_unicode_field_name(self):
        """测试中文字段名"""
        schema = Schema({"用户名": Field(type="str", required=True)})

        result = schema.validate({"用户名": "张三"})
        assert result.valid

    def test_validation_result_str(self):
        """测试 ValidationResult 的字符串表示"""
        result = ValidationResult(valid=True)
        assert "valid=True" in str(result)

        result = ValidationResult(
            valid=False,
            errors=[ValidationError("field", "error message", "bad value")],
        )
        assert "valid=False" in str(result)
        assert "field" in str(result)
