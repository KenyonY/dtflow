# DataTransformer 核心 API

## DataTransformer 类

`DataTransformer` 是项目的核心类，提供链式 API 进行数据操作和格式转换。

### 初始化

```python
from data_transformer import DataTransformer

# 创建空实例
dt = DataTransformer()

# 从数据创建
data = [{"text": "hello"}, {"text": "world"}]
dt = DataTransformer(data)
```

### 数据操作方法

#### add()
添加数据项

```python
# 添加单个项
dt.add({"text": "new item"})

# 添加多个项
dt.add([{"text": "item1"}, {"text": "item2"}])
```

#### modify()
修改数据项

```python
# 按索引修改
dt.modify(index=0, updates={"label": "positive"})

# 按条件修改
dt.modify(
    condition=lambda x: x['score'] > 0.5,
    updates={"label": "high"}
)

# 使用转换函数
dt.modify(
    condition=lambda x: 'text' in x,
    transform=lambda x: {**x, 'text': x['text'].upper()}
)
```

#### delete()
删除数据项

```python
# 按索引删除
dt.delete(index=0)

# 按条件删除
dt.delete(condition=lambda x: x['score'] < 0.3)
```

#### filter()
过滤数据

```python
# 保留满足条件的项
dt.filter(lambda x: x['score'] > 0.5)
```

#### map()
转换所有数据项

```python
# 应用转换函数
dt.map(lambda x: {**x, 'processed': True})
```

### 数据查询方法

#### count()
计数

```python
# 统计所有项
total = dt.count()

# 条件计数
positive = dt.count(lambda x: x['label'] == 'positive')
```

#### similarity()
计算相似度

```python
# 计算两个项的相似度
score = dt.similarity(0, 1, method='cosine', text_field='text')
```

#### find_similar()
查找相似项

```python
# 查找最相似的5个项
similar = dt.find_similar(reference=0, top_k=5, method='cosine')
# 返回: [(index, score), ...]
```

#### stats()
获取统计信息

```python
stats = dt.stats()
# 返回: {"total": 100, "fields": [...], "field_stats": {...}}
```

### 格式转换方法

#### to_sft()
转换为 SFT 格式

```python
sft_data = dt.to_sft(style="messages")
```

#### to_rlhf()
转换为 RLHF 格式

```python
rlhf_data = dt.to_rlhf(style="pair")
```

#### to_pretrain()
转换为预训练格式

```python
pretrain_data = dt.to_pretrain()
```

#### from_format()
从特定格式加载

```python
dt.from_format(data, format_type="sft")
```

### 保存和加载

#### save()
保存数据

```python
# 保存为 JSONL
dt.save("output.jsonl")

# 转换格式后保存
dt.save("output.jsonl", format_type="sft", file_format="jsonl")

# 保存为 CSV
dt.save("output.csv", file_format="csv")
```

#### load() (类方法)
加载数据

```python
# 从文件加载
dt = DataTransformer.load("data.jsonl")

# 指定源格式
dt = DataTransformer.load("data.jsonl", source_format="sft")

# 加载 CSV
dt = DataTransformer.load("data.csv", file_format="csv")
```

### 工具方法

#### copy()
深拷贝

```python
dt_copy = dt.copy()
```

#### clear()
清空数据

```python
dt.clear()
```

#### shuffle()
随机打乱

```python
dt.shuffle(seed=42)
```

#### split()
分割数据集

```python
train, test = dt.split(ratio=0.8, shuffle=True, seed=42)
```

## 方法链式调用

所有修改方法都返回 `self`，支持链式调用：

```python
result = (DataTransformer()
    .add([{"text": "a"}, {"text": "b"}])
    .filter(lambda x: len(x['text']) > 0)
    .map(lambda x: {**x, 'processed': True})
    .shuffle(seed=42))
```

## 魔术方法

```python
# 长度
len(dt)  # 返回数据项数量

# 索引访问
dt[0]  # 获取第一项
dt[1:3]  # 切片

# 字符串表示
repr(dt)  # DataTransformer(samples=100)
```

## 参考

完整源码：[data_transformer/core.py](../../data_transformer/core.py:1)
