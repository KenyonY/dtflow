# 格式转换器 API

DataTransformer 支持多种机器学习训练格式的相互转换。

## 支持的格式

### 1. SFT (Supervised Fine-Tuning)

监督微调格式，用于指令微调任务。

#### 格式样式

**messages 样式**（推荐）
```json
{
  "messages": [
    {"role": "system", "content": "你是一个helpful助手"},
    {"role": "user", "content": "什么是机器学习？"},
    {"role": "assistant", "content": "机器学习是..."}
  ]
}
```

**prompt-completion 样式**
```json
{
  "prompt": "什么是机器学习？",
  "completion": "机器学习是..."
}
```

#### 使用

```python
# 转换为 SFT 格式
sft_data = dt.to_sft(style="messages")

# 从 SFT 格式加载
dt = DataTransformer.load("data.jsonl", source_format="sft")
```

### 2. RLHF (Reinforcement Learning from Human Feedback)

人类反馈强化学习格式，用于偏好学习。

#### 格式样式

**pair 样式**（成对比较）
```json
{
  "prompt": "写一首诗",
  "chosen": "优选回答...",
  "rejected": "较差回答..."
}
```

**ranking 样式**（排序）
```json
{
  "prompt": "写一首诗",
  "responses": ["回答1", "回答2", "回答3"],
  "ranking": [0, 2, 1]  // 0是最好的
}
```

#### 使用

```python
# 转换为 RLHF 格式
rlhf_data = dt.to_rlhf(style="pair")

# 从 RLHF 格式加载
dt = DataTransformer.load("data.jsonl", source_format="rlhf")
```

### 3. Pretrain

预训练格式，纯文本语料。

#### 格式

```json
{
  "text": "这是一段预训练文本..."
}
```

#### 使用

```python
# 转换为预训练格式
pretrain_data = dt.to_pretrain()

# 从预训练格式加载
dt = DataTransformer.load("data.jsonl", source_format="pretrain")
```

## 格式转换器基类

所有格式转换器都继承自 `BaseFormatter`。

### BaseFormatter

```python
from data_transformer.formats.base import BaseFormatter

class CustomFormatter(BaseFormatter):
    def format(self, item: Dict) -> Dict:
        """将数据项转换为目标格式"""
        pass

    def parse(self, item: Dict) -> Dict:
        """从目标格式解析回通用格式"""
        pass
```

### 实现自定义格式转换器

```python
from data_transformer.formats.base import BaseFormatter

class MyCustomFormatter(BaseFormatter):
    def format(self, item: Dict) -> Dict:
        # 实现转换逻辑
        return {
            "custom_field": item.get("text", "")
        }

    def parse(self, item: Dict) -> Dict:
        # 实现解析逻辑
        return {
            "text": item.get("custom_field", "")
        }

# 注册自定义格式
dt._formatters['custom'] = MyCustomFormatter()

# 使用
dt.save("output.jsonl", format_type="custom")
```

## 参考

- SFT 格式转换器：[data_transformer/formats/sft.py](../../data_transformer/formats/sft.py:1)
- RLHF 格式转换器：[data_transformer/formats/rlhf.py](../../data_transformer/formats/rlhf.py:1)
- Pretrain 格式转换器：[data_transformer/formats/pretrain.py](../../data_transformer/formats/pretrain.py:1)
- 基类：[data_transformer/formats/base.py](../../data_transformer/formats/base.py:1)
