# 设计原则

DataTransformer 项目遵循以下核心设计原则：

## 1. KISS 原则

**Keep It Simple, Stupid**

- 优先选择简单直接的解决方案
- 避免过度设计和不必要的抽象
- 代码应该易于理解和维护

### 实践示例

✅ **好的做法**:
```python
# 简单直接的数据转换
def to_sft(data):
    return [{"messages": item["conversations"]} for item in data]
```

❌ **避免**:
```python
# 过度设计的工厂模式
class SFTConverterFactory:
    def create_converter(self, strategy):
        # 不必要的复杂性
        pass
```

## 2. 组合大于继承

- 尽可能少地使用继承
- 优先使用组合和委托
- 保持类层次扁平

### 实践示例

✅ **好的做法**:
```python
class DataTransformer:
    def __init__(self):
        # 组合：使用格式转换器
        self._formatters = {
            'sft': SFTFormatter(),
            'rlhf': RLHFFormatter()
        }
```

❌ **避免**:
```python
# 深层继承链
class BaseTransformer:
    pass

class AdvancedTransformer(BaseTransformer):
    pass

class SuperAdvancedTransformer(AdvancedTransformer):
    pass
```

## 3. 单一职责原则

每个类或模块应该只有一个变化的理由。

### 模块职责划分

- **data_transformer/core.py**: 数据操作和转换
- **data_transformer/formats/**: 格式解析和转换
- **data_transformer/storage/**: 文件读写
- **data_transformer/utils/**: 工具函数

## 4. 契约式编程

特别是在 `light_transformer` 框架中：

```python
from light_transformer.core.base import BaseProcessor
from light_transformer.core.contract import DataContract

class MyProcessor(BaseProcessor):
    def process(self, data: str) -> str:  # 类型注解即契约
        return data.upper()
```

- 使用类型注解定义输入输出契约
- 在运行时验证类型匹配
- 提前发现类型错误

## 5. 链式 API 设计

提供流畅的链式调用接口：

```python
result = (DataTransformer()
    .add(data)
    .filter(lambda x: x['score'] > 0.5)
    .map(lambda x: process(x))
    .to_sft())
```

### 实现要点

- 修改方法返回 `self`
- 保持方法简洁
- 避免副作用

## 6. 显式优于隐式

- 明确的参数传递
- 清晰的错误消息
- 避免魔法行为

✅ **好的做法**:
```python
dt.save("output.jsonl", format_type="sft", file_format="jsonl")
```

❌ **避免**:
```python
dt.save("output.jsonl")  # 隐式推断格式
```

## 7. 配置集中化

所有配置应该集中管理：

```python
# label-app/backend/app/config.py
class Settings(BaseSettings):
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024
    ALLOWED_UPLOAD_EXTENSIONS: set = {'.jsonl', '.json'}
```

### 好处

- 易于修改和维护
- 支持环境变量覆盖
- 类型安全

## 8. 错误处理一致性

使用自定义异常类：

```python
# 定义明确的异常
class DatasetNotFoundError(DataTransformerError):
    def __init__(self, dataset_id: str):
        super().__init__(f"Dataset '{dataset_id}' not found")

# 使用
raise DatasetNotFoundError("ds_001")
```

## 9. 测试驱动开发

- 编写测试覆盖核心功能
- 使用 pytest 进行测试
- 目标覆盖率 > 80%

```python
def test_add_item():
    dt = DataTransformer()
    dt.add({"text": "test"})
    assert len(dt) == 1
```

## 10. 文档即代码

- 每个模块一个文档
- 保持文档与代码同步
- 使用类型注解和 docstring

```python
def similarity(
    self,
    index1: int,
    index2: int,
    method: str = 'cosine',
    text_field: str = 'text'
) -> float:
    """
    计算两个数据项的相似度。

    Args:
        index1: 第一个项的索引
        index2: 第二个项的索引
        method: 相似度计算方法
        text_field: 用于比较的文本字段

    Returns:
        相似度分数（0-1之间）
    """
```

## 反模式（要避免的）

### ❌ 1. 过早优化

在性能成为问题之前不要优化。

### ❌ 2. 魔法数字

使用命名常量而不是硬编码数字：

```python
# 好
MAX_UPLOAD_SIZE = 100 * 1024 * 1024

# 差
if size > 104857600:  # 这是什么？
```

### ❌ 3. 全局状态

避免使用全局变量，使用依赖注入：

```python
# 好
def process(data, storage: StorageManager):
    storage.save(data)

# 差
global_storage = StorageManager()
def process(data):
    global_storage.save(data)
```

### ❌ 4. 过度使用继承

参考"组合大于继承"原则。

## 代码审查清单

在提交代码前检查：

- [ ] 是否遵循 KISS 原则？
- [ ] 是否可以用组合替代继承？
- [ ] 每个函数是否只做一件事？
- [ ] 是否有足够的类型注解？
- [ ] 错误消息是否清晰？
- [ ] 是否有测试覆盖？
- [ ] 文档是否更新？

## 参考

- [Python 之禅](https://www.python.org/dev/peps/pep-0020/)
- [Clean Code](https://www.oreilly.com/library/view/clean-code-a/9780136083238/)
- [SOLID 原则](https://en.wikipedia.org/wiki/SOLID)
