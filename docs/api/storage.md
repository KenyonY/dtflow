# 存储后端 API

## FlaxKVStorageManager

高性能 FlaxKV2 键值数据库存储管理器。

### 初始化

```python
from label_app.backend.app.core.storage_flaxkv import FlaxKVStorageManager

storage = FlaxKVStorageManager(data_dir="data/flaxkv")
```

### 数据集操作

#### list_datasets()
获取所有数据集列表

```python
datasets = storage.list_datasets()
# 返回: [{"id": "ds_001", "name": "...", "type": "sft", ...}, ...]
```

#### get_dataset()
获取单个数据集

```python
dataset = storage.get_dataset("ds_001")
# 返回: {"id": "ds_001", "name": "...", ...} 或 None
```

#### create_dataset()
创建新数据集

```python
dataset = storage.create_dataset(
    name="我的数据集",
    dataset_type="sft",
    description="示例数据集"
)
# 返回: {"id": "ds_001", "name": "我的数据集", ...}
```

#### delete_dataset()
删除数据集

```python
success = storage.delete_dataset("ds_001")
# 返回: True 或 False
```

### 数据项操作

#### get_items()
获取数据项列表（分页）

```python
items, total = storage.get_items(
    dataset_id="ds_001",
    skip=0,
    limit=100,
    status_filter="pending",  # 可选: "pending", "annotated"
    sample_size=None  # 可选: 随机采样大小
)
# 返回: ([数据项列表], 总数)
```

#### get_item()
获取单个数据项

```python
item = storage.get_item("ds_001", item_id=0)
# 返回: {"id": 0, "text": "...", ...} 或 None
```

#### add_item()
添加数据项

```python
item = storage.add_item(
    dataset_id="ds_001",
    item_data={"text": "示例文本", "label": "positive"}
)
# 返回: {"id": 0, "text": "...", "status": "pending", ...}
```

#### update_item()
更新数据项

```python
item = storage.update_item(
    dataset_id="ds_001",
    item_id=0,
    updates={"label": "negative", "status": "annotated"}
)
# 返回: 更新后的数据项 或 None
```

#### delete_item()
删除数据项

```python
success = storage.delete_item("ds_001", item_id=0)
# 返回: True 或 False
```

### 标注操作

#### get_next_item()
获取下一个待标注项

```python
item = storage.get_next_item(
    dataset_id="ds_001",
    current_id=0  # 可选: 从当前ID后开始
)
# 返回: 下一个 pending 状态的项 或 None
```

#### annotate_item()
提交标注

```python
item = storage.annotate_item(
    dataset_id="ds_001",
    item_id=0,
    annotation_data={
        "label": "positive",
        "confidence": 0.95,
        "notes": "标注说明"
    }
)
# 返回: 更新后的数据项（状态变为 "annotated"）
```

### 统计信息

#### get_stats()
获取数据集统计

```python
stats = storage.get_stats("ds_001")
# 返回: {
#     "total": 100,
#     "annotated": 50,
#     "pending": 45,
#     "in_progress": 5
# }
```

### 文件操作

#### upload_file()
上传并导入数据文件

```python
count = storage.upload_file(
    dataset_id="ds_001",
    filepath="data.jsonl",
    source_format="sft"  # 可选: "sft", "rlhf", "pretrain"
)
# 返回: 导入的数据项数量
```

#### export_dataset()
导出数据集

```python
export_path = storage.export_dataset(
    dataset_id="ds_001",
    format_type="sft",  # 可选: "sft", "rlhf", "pretrain"
    style="messages"  # 可选: 格式样式
)
# 返回: 导出文件路径
```

### 上下文管理器

```python
# 使用 with 语句自动管理连接
with FlaxKVStorageManager(data_dir="data/flaxkv") as storage:
    datasets = storage.list_datasets()
    # ... 进行操作
# 自动关闭所有数据库连接
```

### 手动关闭

```python
storage.close_all()  # 关闭所有数据库连接
```

## 数据库结构

### 元数据数据库 (metadata)

```
metadata:
  ├─ datasets: {
  │    "ds_001": {数据集信息},
  │    "ds_002": {数据集信息},
  │    ...
  │  }
```

### 数据集数据库 (dataset_{id})

```
dataset_ds_001:
  ├─ _metadata: {统计信息}
  ├─ item:0: {数据项}
  ├─ item:1: {数据项}
  └─ ...
```

## 性能特性

- **读写性能**: 比 JSONL 文件快 10-500 倍
- **并发安全**: 线程安全，支持多进程访问
- **自动序列化**: 自动处理 Python 对象
- **类字典接口**: 简单易用

## 参考

完整源码：[label-app/backend/app/core/storage_flaxkv.py](../../label-app/backend/app/core/storage_flaxkv.py:1)
