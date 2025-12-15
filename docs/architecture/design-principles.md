# 设计原则

dtflow 的核心设计哲学。

## 1. 函数式优于类继承

直接用 lambda/函数做转换，不需要复杂的 OOP 抽象。

### 实践示例

✅ **好的做法**:
```python
# 简单直接的数据转换
dt.to(lambda x: {"q": x.question, "a": x.answer})

# 使用预设函数
dt.to(preset="openai_chat")
```

❌ **避免**:
```python
# 不需要这种 OOP 设计
class MyFormatter(BaseFormatter):
    def format(self, item):
        return {"q": item["question"], "a": item["answer"]}

# 不需要工厂模式
class FormatterFactory:
    def create_formatter(self, type): ...
```

## 2. 预设是便利层，不是核心抽象

90% 的需求用 `transform(lambda x: ...)` 就能解决。预设只是常见场景的快捷方式。

### 实践示例

```python
# 预设：常见场景的便利函数
dt.to(preset="openai_chat")
dt.to(preset="alpaca")

# 自定义：完全控制转换逻辑
dt.to(lambda x: {
    "messages": [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": x.question},
        {"role": "assistant", "content": x.answer}
    ]
})
```

预设函数在 `dtflow/presets.py` 中定义，它们本身也是返回 lambda 的工厂函数。

## 3. KISS 原则

**Keep It Simple, Stupid**

- 一个核心类 `DataTransformer` 搞定所有操作
- 不追求"可扩展框架"
- 不过度设计
- 代码应该易于理解和维护

### 模块职责划分

- **dtflow/core.py**: DataTransformer 核心类
- **dtflow/presets.py**: 预设转换函数
- **dtflow/storage/**: 文件读写
- **dtflow/cli/**: 命令行工具

## 4. 链式 API 设计

提供流畅的链式调用接口：

```python
(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8)
    .to(lambda x: {"q": x.question, "a": x.answer})
    .save("output.jsonl"))
```

### 实现要点

- 修改方法返回 `self`
- DictWrapper 提供属性访问 `x.field` 代替 `x["field"]`
- 保持方法简洁

## 5. 实用主义

不追求学术上的完美抽象，只提供**足够好用的工具**。

- 不需要反向解析 (parse)，因为实际场景很少需要
- 不需要格式注册表，因为 lambda 足够灵活
- 不需要类型验证框架，因为 Python 本身足够动态

## 6. 错误处理

提供灵活的错误处理策略：

```python
# 跳过错误项（默认）
dt.to(transform_func, on_error="skip")

# 抛出异常
dt.to(transform_func, on_error="raise")

# 保留原始数据
dt.to(transform_func, on_error="keep")

# 返回错误详情
result, errors = dt.to(transform_func, return_errors=True)
```

## 反模式（要避免的）

### ❌ 1. 过度抽象

```python
# 不需要
class BaseFormatter(ABC):
    @abstractmethod
    def format(self, item): ...
    @abstractmethod
    def parse(self, item): ...

class FormatRegistry:
    def register(self, name, formatter): ...
```

### ❌ 2. 过早优化

在性能成为问题之前不要优化。

### ❌ 3. 深层继承

保持类层次扁平，优先使用组合。

## 代码审查清单

在提交代码前检查：

- [ ] 是否遵循 KISS 原则？
- [ ] 能否用 lambda 代替类？
- [ ] 是否过度设计？
- [ ] 链式 API 是否流畅？

## 参考

- [Python 之禅](https://www.python.org/dev/peps/pep-0020/)
- "Simple is better than complex."
- "Flat is better than nested."
