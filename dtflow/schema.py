"""
Schema 验证模块

提供轻量级的数据结构验证，支持字段路径语法。

用法:
    from dtflow import Schema, Field

    # 定义 Schema
    schema = Schema({
        "messages": Field(type="list", required=True, min_length=1),
        "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
        "messages[*].content": Field(type="str", min_length=1),
        "score": Field(type="float", min=0, max=1),
    })

    # 验证单条数据
    result = schema.validate(item)
    if result.valid:
        print("验证通过")
    else:
        print(f"验证失败: {result.errors}")

    # 验证整个数据集
    dt = DataTransformer.load("data.jsonl")
    results = dt.validate_schema(schema)
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Union

from .utils.field_path import get_field, _parse_path, _get_value_by_segments

# 支持的类型
FieldType = Literal["str", "int", "float", "bool", "list", "dict", "any"]

# 类型映射
_TYPE_MAP: Dict[str, type] = {
    "str": str,
    "int": int,
    "float": (int, float),  # type: ignore  # float 也接受 int
    "bool": bool,
    "list": list,
    "dict": dict,
}


@dataclass
class ValidationError:
    """单个验证错误"""

    path: str  # 字段路径
    message: str  # 错误信息
    value: Any = None  # 实际值（可选）

    def __str__(self) -> str:
        if self.value is not None:
            return f"{self.path}: {self.message} (got: {self.value!r})"
        return f"{self.path}: {self.message}"


@dataclass
class ValidationResult:
    """验证结果"""

    valid: bool
    errors: List[ValidationError] = dataclass_field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid

    def __str__(self) -> str:
        if self.valid:
            return "ValidationResult(valid=True)"
        error_strs = [str(e) for e in self.errors[:5]]
        if len(self.errors) > 5:
            error_strs.append(f"... and {len(self.errors) - 5} more errors")
        return f"ValidationResult(valid=False, errors=[{', '.join(error_strs)}])"


@dataclass
class Field:
    """
    字段定义

    Args:
        type: 期望的类型，可选 "str", "int", "float", "bool", "list", "dict", "any"
        required: 是否必填（默认 False，明确标记才是必填）
        nullable: 是否允许 None（默认 False）
        min: 最小值（数值类型）
        max: 最大值（数值类型）
        min_length: 最小长度（字符串或列表）
        max_length: 最大长度（字符串或列表）
        choices: 允许的值列表
        pattern: 正则表达式模式（字符串类型）
        custom: 自定义验证函数，接收值返回 True/False 或错误信息字符串

    Examples:
        >>> Field(type="str", required=True, min_length=1)
        >>> Field(type="int", min=0, max=100)
        >>> Field(type="str", choices=["user", "assistant", "system"])
        >>> Field(type="float", min=0, max=1, nullable=True)
    """

    type: FieldType = "any"
    required: bool = False  # 默认非必填，明确标记才是必填
    nullable: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    choices: Optional[List[Any]] = None
    pattern: Optional[str] = None
    custom: Optional[Callable[[Any], Union[bool, str]]] = None

    def validate(self, value: Any, path: str = "") -> List[ValidationError]:
        """
        验证单个值

        Args:
            value: 要验证的值
            path: 字段路径（用于错误信息）

        Returns:
            验证错误列表（空列表表示验证通过）
        """
        errors: List[ValidationError] = []

        # 检查 None
        if value is None:
            if self.nullable:
                return []  # None 是允许的，跳过后续检查
            if self.required:
                errors.append(ValidationError(path, "字段不能为 None", value))
            return errors

        # 类型检查
        if self.type != "any":
            expected_type = _TYPE_MAP.get(self.type)
            if expected_type and not isinstance(value, expected_type):
                errors.append(
                    ValidationError(
                        path, f"类型错误，期望 {self.type}，实际 {type(value).__name__}", value
                    )
                )
                return errors  # 类型错误，跳过后续检查

        # 数值范围检查
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min is not None and value < self.min:
                errors.append(ValidationError(path, f"值不能小于 {self.min}", value))
            if self.max is not None and value > self.max:
                errors.append(ValidationError(path, f"值不能大于 {self.max}", value))

        # 长度检查
        if isinstance(value, (str, list, tuple)):
            length = len(value)
            if self.min_length is not None and length < self.min_length:
                errors.append(ValidationError(path, f"长度不能小于 {self.min_length}", length))
            if self.max_length is not None and length > self.max_length:
                errors.append(ValidationError(path, f"长度不能大于 {self.max_length}", length))

        # 选项检查
        if self.choices is not None and value not in self.choices:
            errors.append(
                ValidationError(path, f"值必须是 {self.choices} 之一", value)
            )

        # 正则表达式检查
        if self.pattern is not None and isinstance(value, str):
            import re

            if not re.match(self.pattern, value):
                errors.append(ValidationError(path, f"不匹配模式 {self.pattern}", value))

        # 自定义验证
        if self.custom is not None:
            try:
                result = self.custom(value)
                if result is False:
                    errors.append(ValidationError(path, "自定义验证失败", value))
                elif isinstance(result, str):
                    errors.append(ValidationError(path, result, value))
            except Exception as e:
                errors.append(ValidationError(path, f"自定义验证异常: {e}", value))

        return errors


class Schema:
    """
    数据结构验证 Schema

    支持字段路径语法定义嵌套结构的验证规则。

    Args:
        fields: 字段定义字典，键为字段路径，值为 Field 对象

    Examples:
        >>> schema = Schema({
        ...     "messages": Field(type="list", required=True, min_length=1),
        ...     "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
        ...     "messages[*].content": Field(type="str", min_length=1),
        ...     "score": Field(type="float", min=0, max=1, required=False),
        ... })

        >>> result = schema.validate({"messages": [{"role": "user", "content": "hello"}]})
        >>> result.valid
        True
    """

    def __init__(self, fields: Dict[str, Field]):
        self._fields = fields
        # 分离普通字段和展开字段（包含 [*]）
        self._regular_fields: Dict[str, Field] = {}
        self._expand_fields: Dict[str, Field] = {}

        for path, field_def in fields.items():
            if "[*]" in path:
                self._expand_fields[path] = field_def
            else:
                self._regular_fields[path] = field_def

    def validate(self, data: dict) -> ValidationResult:
        """
        验证单条数据

        Args:
            data: 要验证的字典数据

        Returns:
            ValidationResult 对象
        """
        if not isinstance(data, dict):
            return ValidationResult(
                valid=False,
                errors=[ValidationError("", "数据必须是字典类型", type(data).__name__)],
            )

        errors: List[ValidationError] = []

        # 验证普通字段
        for path, field_def in self._regular_fields.items():
            value = get_field(data, path)

            # 字段不存在
            if value is None and field_def.required:
                # 区分「字段不存在」和「字段值为 None」
                if not self._field_exists(data, path):
                    errors.append(ValidationError(path, "必填字段缺失"))
                    continue

            field_errors = field_def.validate(value, path)
            errors.extend(field_errors)

        # 验证展开字段（包含 [*]）
        for path, field_def in self._expand_fields.items():
            expand_errors = self._validate_expand_field(data, path, field_def)
            errors.extend(expand_errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _field_exists(self, data: dict, path: str) -> bool:
        """检查字段是否存在（区分不存在和值为 None）"""
        segments = _parse_path(path)
        current = data

        for seg in segments:
            if current is None:
                return False
            if isinstance(seg, str):
                if isinstance(current, dict):
                    if seg not in current:
                        return False
                    current = current[seg]
                else:
                    return False
            elif isinstance(seg, int):
                if isinstance(current, (list, tuple)):
                    try:
                        current = current[seg]
                    except IndexError:
                        return False
                else:
                    return False

        return True

    def _validate_expand_field(
        self, data: dict, path: str, field_def: Field
    ) -> List[ValidationError]:
        """验证包含 [*] 的展开字段"""
        errors: List[ValidationError] = []

        # 分割路径：[*] 之前的部分和之后的部分
        parts = path.split("[*]", 1)
        prefix = parts[0].rstrip(".")
        suffix = parts[1].lstrip(".") if len(parts) > 1 else ""

        # 获取数组
        array = get_field(data, prefix) if prefix else data

        if array is None:
            # 如果前缀字段不存在，由普通字段验证处理
            return errors

        if not isinstance(array, (list, tuple)):
            errors.append(ValidationError(prefix, "期望是数组类型", type(array).__name__))
            return errors

        # 对数组中的每个元素验证
        for i, item in enumerate(array):
            actual_path = f"{prefix}[{i}]" if prefix else f"[{i}]"

            if suffix:
                # 有后缀，获取嵌套值
                value = get_field(item, suffix) if isinstance(item, dict) else None
                actual_path = f"{actual_path}.{suffix}"
            else:
                value = item

            field_errors = field_def.validate(value, actual_path)
            errors.extend(field_errors)

        return errors

    def validate_batch(
        self, data: List[dict], max_errors: int = 100
    ) -> List[tuple]:
        """
        批量验证数据

        Args:
            data: 数据列表
            max_errors: 最大错误数量（超过后停止）

        Returns:
            [(index, ValidationResult), ...] 失败记录列表
        """
        failed: List[tuple] = []
        error_count = 0

        for i, item in enumerate(data):
            result = self.validate(item)
            if not result.valid:
                failed.append((i, result))
                error_count += len(result.errors)
                if error_count >= max_errors:
                    break

        return failed

    def __repr__(self) -> str:
        field_strs = [f"  {path}: {field_def}" for path, field_def in self._fields.items()]
        return f"Schema({{\n" + ",\n".join(field_strs) + "\n}})"


# ============================================================================
# 预定义 Schema 模板
# ============================================================================


def openai_chat_schema(
    min_messages: int = 1,
    max_messages: Optional[int] = None,
    roles: Optional[List[str]] = None,
) -> Schema:
    """
    OpenAI Chat 格式的 Schema

    Args:
        min_messages: 最少消息数（默认 1）
        max_messages: 最多消息数（默认不限）
        roles: 允许的角色列表（默认 ["system", "user", "assistant"]）

    Returns:
        Schema 对象

    Examples:
        >>> schema = openai_chat_schema()
        >>> result = schema.validate({"messages": [{"role": "user", "content": "hi"}]})
    """
    if roles is None:
        roles = ["system", "user", "assistant"]

    fields = {
        "messages": Field(
            type="list",
            required=True,
            min_length=min_messages,
            max_length=max_messages,
        ),
        "messages[*].role": Field(type="str", required=True, choices=roles),
        "messages[*].content": Field(type="str", required=True, min_length=1),
    }

    return Schema(fields)


def alpaca_schema(
    require_input: bool = False,
    min_output_length: int = 1,
) -> Schema:
    """
    Alpaca 格式的 Schema

    Args:
        require_input: input 字段是否必填（默认 False）
        min_output_length: output 最小长度（默认 1）

    Returns:
        Schema 对象
    """
    return Schema(
        {
            "instruction": Field(type="str", required=True, min_length=1),
            "input": Field(type="str", required=require_input),
            "output": Field(type="str", required=True, min_length=min_output_length),
        }
    )


def dpo_schema(
    min_chosen_length: int = 1,
    min_rejected_length: int = 1,
) -> Schema:
    """
    DPO 偏好对格式的 Schema

    Args:
        min_chosen_length: chosen 最小长度
        min_rejected_length: rejected 最小长度

    Returns:
        Schema 对象
    """
    return Schema(
        {
            "prompt": Field(type="str", required=True, min_length=1),
            "chosen": Field(type="str", required=True, min_length=min_chosen_length),
            "rejected": Field(type="str", required=True, min_length=min_rejected_length),
        }
    )


def sharegpt_schema(
    min_conversations: int = 1,
    human_role: str = "human",
    gpt_role: str = "gpt",
) -> Schema:
    """
    ShareGPT 多轮对话格式的 Schema

    Args:
        min_conversations: 最少对话轮数
        human_role: 用户角色名
        gpt_role: 助手角色名

    Returns:
        Schema 对象
    """
    return Schema(
        {
            "conversations": Field(
                type="list", required=True, min_length=min_conversations
            ),
            "conversations[*].from": Field(
                type="str", required=True, choices=[human_role, gpt_role]
            ),
            "conversations[*].value": Field(type="str", required=True, min_length=1),
        }
    )


# ============================================================================
# 便捷函数
# ============================================================================


def validate_data(data: Union[dict, List[dict]], schema: Schema) -> ValidationResult:
    """
    便捷函数：验证单条或多条数据

    Args:
        data: 单条数据（dict）或数据列表（List[dict]）
        schema: Schema 对象

    Returns:
        ValidationResult（如果是列表，返回汇总结果）
    """
    if isinstance(data, dict):
        return schema.validate(data)

    # 批量验证
    all_errors: List[ValidationError] = []
    for i, item in enumerate(data):
        result = schema.validate(item)
        if not result.valid:
            for err in result.errors:
                all_errors.append(
                    ValidationError(
                        path=f"[{i}].{err.path}" if err.path else f"[{i}]",
                        message=err.message,
                        value=err.value,
                    )
                )

    return ValidationResult(valid=len(all_errors) == 0, errors=all_errors)
