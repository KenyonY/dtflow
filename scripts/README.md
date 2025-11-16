# 数据集上传工具

本目录包含用于准备和上传数据集的实用脚本。

## 可用脚本

### upload_sft_dataset.py

用于验证和上传 SFT（Supervised Fine-Tuning）数据集的命令行工具。

#### 功能特性

- ✅ 完整的数据格式验证
- ✅ 支持多模态数据（文本 + 图片）
- ✅ 详细的错误报告
- ✅ 自动创建数据集并上传
- ✅ 显示上传统计信息

#### 使用方法

**1. 仅验证数据格式（不上传）**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --validate-only
```

**2. 验证并上传数据**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "医疗问答数据集 V1" \
  --description "包含100条医疗相关问答"
```

**3. 指定 API 服务器地址**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集" \
  --api http://192.168.1.100:8000
```

**4. 转换其他格式数据**

```bash
python scripts/upload_sft_dataset.py \
  --file data/other_format.jsonl \
  --name "转换数据集" \
  --source-format rlhf
```

#### 参数说明

| 参数 | 简写 | 必需 | 说明 |
|------|------|------|------|
| `--file` | `-f` | ✓ | 数据文件路径（JSONL 格式） |
| `--name` | `-n` | * | 数据集名称（上传时必需） |
| `--description` | `-d` | ✗ | 数据集描述 |
| `--api` | - | ✗ | API 服务器地址（默认: http://localhost:8000） |
| `--validate-only` | - | ✗ | 仅验证格式，不上传 |
| `--source-format` | - | ✗ | 源格式（sft/rlhf/pretrain），用于格式转换 |

#### 输出示例

```
📁 正在处理文件: data/sft_dataset_example.jsonl
============================================================
🔍 验证数据格式...
✅ 数据格式验证通过！共 6 条数据

📦 创建数据集: 医疗问答数据集 V1
✅ 数据集创建成功！ID: ds_abc123

⬆️  上传数据文件...
✅ Successfully uploaded 6 items

📊 获取数据集统计...
✅ 统计信息:
   • 总数: 6
   • 已标注: 0
   • 待标注: 6

============================================================
🎉 数据集上传完成！

访问 Web 界面开始标注:
  http://localhost:5173/datasets

或直接开始标注:
  http://localhost:5173/annotate/sft/ds_abc123
```

#### 错误处理

脚本会检测以下常见错误：

- JSON 格式错误
- 缺少必需字段（`messages`）
- 无效的角色类型（`role`）
- 空内容（`content`）
- 多模态内容格式错误
- 文件编码问题

示例错误输出：

```
❌ 发现 3 个错误:

  • 第 5 行: 缺少 'messages' 字段
  • 第 8 行，消息 1: 无效的 role 'bot'（必须是 'system', 'user', 或 'assistant'）
  • 第 12 行: JSON 格式错误 - Expecting ',' delimiter: line 1 column 45 (char 44)
```

## 依赖要求

```bash
pip install requests
```

## 快速开始

1. **准备数据文件**

   创建一个 JSONL 文件，每行一个 JSON 对象：

   ```json
   {"messages":[{"role":"user","content":"你好"},{"role":"assistant","content":"你好！有什么可以帮助你的吗？"}]}
   {"messages":[{"role":"user","content":"什么是AI？"},{"role":"assistant","content":"AI（人工智能）是..."}]}
   ```

2. **验证数据**

   ```bash
   python scripts/upload_sft_dataset.py -f my_data.jsonl --validate-only
   ```

3. **上传数据**

   ```bash
   python scripts/upload_sft_dataset.py -f my_data.jsonl -n "我的数据集"
   ```

4. **开始标注**

   在浏览器中访问提示的 URL 开始标注工作。

## 数据格式参考

详细的数据格式说明请参考：[SFT数据集上传指南.md](../SFT数据集上传指南.md)

示例数据文件：[data/sft_dataset_example.jsonl](../data/sft_dataset_example.jsonl)

## 故障排除

### 连接错误

如果遇到连接错误：

```
❌ 创建数据集失败: HTTPConnectionPool(host='localhost', port=8000)
```

请确认：
1. 后端服务是否正在运行
2. API 地址是否正确
3. 防火墙设置

启动后端服务：

```bash
cd label-app/backend
python run.py
```

### 编码错误

确保文件使用 UTF-8 编码：

```bash
# 检查文件编码
file -I my_data.jsonl

# 转换编码
iconv -f GBK -t UTF-8 my_data.jsonl > my_data_utf8.jsonl
```

### 超时错误

对于大文件，可能需要增加超时时间。可以修改脚本中的 `timeout` 参数。

## 贡献

欢迎提交问题和改进建议！
