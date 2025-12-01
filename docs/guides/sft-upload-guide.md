# SFT 数据集上传指南

本指南介绍如何准备和上传 SFT（Supervised Fine-Tuning）标注数据集到 DataTransformer 平台。

## 📋 目录
- [数据格式要求](#数据格式要求)
- [支持的格式](#支持的格式)
- [数据示例](#数据示例)
- [上传步骤](#上传步骤)
- [常见问题](#常见问题)

## 数据格式要求

### 基本结构

SFT 数据集使用 **JSONL** 格式（每行一个JSON对象），每条数据包含一个对话。

**必需字段：**
- `messages`: 消息数组，包含完整的对话历史

**消息（Message）结构：**
```typescript
{
  "role": "system" | "user" | "assistant",  // 角色
  "content": string | ContentItem[]         // 内容（文本或多模态）
}
```

### 支持的角色类型

- `system`: 系统提示词，定义 AI 的行为和规则
- `user`: 用户输入的问题或指令
- `assistant`: AI 助手的回复

### 多模态支持

内容支持纯文本或包含图片的多模态格式：

**纯文本：**
```json
{
  "role": "user",
  "content": "什么是机器学习？"
}
```

**多模态（文本+图片）：**
```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "请描述这张图片"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "https://example.com/image.jpg",
        "detail": "high"  // 可选: auto, low, high
      }
    }
  ]
}
```

## 支持的格式

上传时系统支持以下文件格式：

| 格式 | 扩展名 | 说明 |
|-----|--------|------|
| JSONL | `.jsonl` | 推荐格式，每行一个JSON对象 |
| JSON | `.json` | JSON数组格式 |
| CSV | `.csv` | CSV格式（需包含适当的列） |

## 数据示例

### 示例 1: 简单问答（带系统提示）

```json
{
  "messages": [
    {
      "role": "system",
      "content": "你是一个专业的AI助手，请友好、准确地回答用户问题。"
    },
    {
      "role": "user",
      "content": "什么是机器学习？"
    },
    {
      "role": "assistant",
      "content": "机器学习是人工智能的一个分支，它使计算机系统能够从数据中学习和改进，而无需显式编程..."
    }
  ]
}
```

### 示例 2: 代码生成任务

```json
{
  "messages": [
    {
      "role": "user",
      "content": "请帮我写一个Python函数来计算斐波那契数列"
    },
    {
      "role": "assistant",
      "content": "当然！这里是一个计算斐波那契数列的Python函数：\n\n```python\ndef fibonacci(n):\n    if n <= 0:\n        return 0\n    elif n == 1:\n        return 1\n    else:\n        return fibonacci(n-1) + fibonacci(n-2)\n```"
    }
  ]
}
```

### 示例 3: 多轮对话

```json
{
  "messages": [
    {
      "role": "system",
      "content": "你是一个编程教学助手。"
    },
    {
      "role": "user",
      "content": "什么是闭包？"
    },
    {
      "role": "assistant",
      "content": "闭包是一个函数能够记住并访问它被创建时所在的作用域..."
    },
    {
      "role": "user",
      "content": "能举个JavaScript的例子吗？"
    },
    {
      "role": "assistant",
      "content": "当然！这里是一个经典的闭包例子：\n\n```javascript\nfunction createCounter() {\n    let count = 0;\n    return function() {\n        count++;\n        return count;\n    };\n}\n```"
    }
  ]
}
```

### 示例 4: 多模态（图文）

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "请描述这张图片中的内容"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://example.com/image.jpg",
            "detail": "high"
          }
        }
      ]
    },
    {
      "role": "assistant",
      "content": "图片中显示了..."
    }
  ]
}
```

## 上传步骤

### 方法一：通过 Web 界面上传

1. **访问数据集页面**
   - 打开浏览器访问：`http://localhost:5173/datasets`（或您的部署地址）

2. **创建新数据集**
   - 点击 "New Dataset" 按钮
   - 填写数据集信息：
     - 名称：如 "医疗问答数据集 V1"
     - 类型：选择 "SFT (Supervised Fine-Tuning)"
     - 描述（可选）：数据集的详细说明

3. **上传数据文件**
   - 在数据集卡片上点击 "Upload" 按钮
   - 拖拽文件或点击选择文件
   - 支持的格式：`.jsonl`, `.json`, `.csv`
   - 等待上传完成

4. **开始标注**
   - 上传成功后，点击 "Start Annotating" 开始标注工作
   - 或点击 "Review" 查看已标注的数据

### 方法二：通过 API 上传

```bash
# 创建数据集
curl -X POST http://localhost:8000/api/datasets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SFT 示例数据集",
    "type": "sft",
    "description": "用于测试的SFT数据集"
  }'

# 上传数据文件（假设得到的 dataset_id 为 "dataset_123"）
curl -X POST http://localhost:8000/api/datasets/dataset_123/upload \
  -F "file=@/path/to/your/data.jsonl"
```

### 方法三：使用 Python 脚本

```python
import requests

API_BASE = "http://localhost:8000"

# 1. 创建数据集
response = requests.post(
    f"{API_BASE}/api/datasets",
    json={
        "name": "SFT 示例数据集",
        "type": "sft",
        "description": "用于测试的SFT数据集"
    }
)
dataset = response.json()
dataset_id = dataset["id"]

# 2. 上传数据文件
with open("sft_dataset_example.jsonl", "rb") as f:
    files = {"file": f}
    response = requests.post(
        f"{API_BASE}/api/datasets/{dataset_id}/upload",
        files=files
    )
    print(response.json())
```

## 数据验证

上传前建议验证数据格式：

### Python 验证脚本

```python
import json

def validate_sft_data(filepath):
    """验证 SFT 数据格式"""
    errors = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line)

                # 检查必需字段
                if 'messages' not in data:
                    errors.append(f"第 {line_num} 行: 缺少 'messages' 字段")
                    continue

                messages = data['messages']
                if not isinstance(messages, list):
                    errors.append(f"第 {line_num} 行: 'messages' 必须是数组")
                    continue

                # 检查每条消息
                for msg_idx, msg in enumerate(messages):
                    if 'role' not in msg:
                        errors.append(f"第 {line_num} 行，消息 {msg_idx}: 缺少 'role' 字段")
                    elif msg['role'] not in ['system', 'user', 'assistant']:
                        errors.append(f"第 {line_num} 行，消息 {msg_idx}: 无效的 role '{msg['role']}'")

                    if 'content' not in msg:
                        errors.append(f"第 {line_num} 行，消息 {msg_idx}: 缺少 'content' 字段")

            except json.JSONDecodeError as e:
                errors.append(f"第 {line_num} 行: JSON 格式错误 - {str(e)}")

    if errors:
        print("❌ 发现以下错误：")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print("✅ 数据格式验证通过！")
        return True

# 使用示例
validate_sft_data("sft_dataset_example.jsonl")
```

## 常见问题

### Q1: 支持哪些文件格式？

**A:** 主要支持 JSONL 格式（推荐），也支持 JSON 和 CSV。JSONL 格式每行一个完整的 JSON 对象，便于流式处理大文件。

### Q2: 单个文件大小有限制吗？

**A:** 理论上没有严格限制，但建议单个文件不超过 100MB。对于更大的数据集，建议分批上传。

### Q3: 是否必须包含 system 消息？

**A:** 不是必须的。可以只包含 user 和 assistant 的对话。但建议添加 system 消息来明确模型的行为规则。

### Q4: 如何处理多轮对话？

**A:** 将所有轮次的消息按时间顺序放在同一个 `messages` 数组中，role 交替出现（user -> assistant -> user -> assistant...）。

### Q5: 图片 URL 支持哪些格式？

**A:** 支持：
- HTTP/HTTPS URL：`https://example.com/image.jpg`
- 本地文件路径：`file:///path/to/image.jpg`
- Base64 编码：`data:image/jpeg;base64,/9j/4AAQ...`

### Q6: 上传失败怎么办？

**A:** 常见原因：
1. 检查 JSON 格式是否正确（可以用在线 JSON 验证工具）
2. 确认文件编码为 UTF-8
3. 检查必需字段是否完整
4. 查看浏览器控制台或服务器日志获取详细错误信息

### Q7: 如何导出已标注的数据？

**A:** 在数据集列表页面，点击数据集卡片上的 "Export" 按钮，选择导出格式即可下载。

## 最佳实践

1. **数据质量**
   - 确保对话内容准确、完整
   - assistant 的回复应当高质量、有帮助
   - 避免有害、偏见或不当内容

2. **格式规范**
   - 使用 UTF-8 编码
   - 保持 JSONL 格式（每行一个完整对象）
   - 合理使用 system 消息设定场景

3. **多样性**
   - 包含不同类型的任务和场景
   - 涵盖不同难度级别的问题
   - 保持对话风格的多样性

4. **版本管理**
   - 为数据集添加清晰的版本号和描述
   - 记录数据来源和标注规则
   - 定期备份导出数据

## 参考资料

- [OpenAI Chat Completions API 格式](https://platform.openai.com/docs/guides/chat)
- [项目完整示例文件](./data/sft_dataset_example.jsonl)
- [后端 API 文档](http://localhost:8000/docs)

## 技术支持

如有问题，请查看：
- 项目 README.md
- 后端日志：`label-app/backend/logs/`
- 前端控制台错误信息

---

**示例数据文件路径：** `data/sft_dataset_example.jsonl`

准备好数据后，访问 http://localhost:5173/datasets 开始上传和标注！
