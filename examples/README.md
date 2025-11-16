# DataTransformer 示例

本目录包含各种使用示例和演示代码。

## 📁 文件列表

### sft_upload_demo.html

一个完整的独立 HTML 页面，展示如何创建和上传 SFT 数据集。

**功能特性：**
- 🎨 美观的现代化界面
- 📤 支持拖拽上传文件
- 📊 实时上传进度显示
- ✅ 表单验证和错误处理
- 🔗 成功后直接跳转到标注页面

**使用方法：**

1. 确保后端服务正在运行：
   ```bash
   cd label-app/backend
   python run.py
   ```

2. 在浏览器中打开示例页面：
   ```bash
   # 方式 1: 直接打开文件
   open examples/sft_upload_demo.html

   # 方式 2: 使用 Python 启动简单 HTTP 服务器
   cd examples
   python -m http.server 8080
   # 然后访问 http://localhost:8080/sft_upload_demo.html
   ```

3. 填写数据集信息并上传文件

**支持的文件格式：**
- `.jsonl` - JSON Lines 格式（推荐）
- `.json` - JSON 数组格式
- `.csv` - CSV 格式

**截图：**

页面包含以下部分：
- 数据集名称和描述输入
- 拖拽上传区域
- 文件信息显示
- 上传进度条
- 数据格式示例代码

## 📚 相关资源

### 文档
- [SFT数据集上传指南](../SFT数据集上传指南.md) - 详细的格式说明和使用指南
- [脚本工具说明](../scripts/README.md) - 命令行工具使用方法

### 示例数据
- [sft_dataset_example.jsonl](../data/sft_dataset_example.jsonl) - 标准 SFT 数据集示例

### 工具脚本
- [upload_sft_dataset.py](../scripts/upload_sft_dataset.py) - Python 命令行上传工具

## 🎯 快速开始

### 方案 1: 使用 Web 界面上传

1. 访问主应用：http://localhost:5173/datasets
2. 点击 "New Dataset" 创建数据集
3. 点击 "Upload" 上传数据文件

### 方案 2: 使用独立示例页面

1. 打开 `sft_upload_demo.html`
2. 填写表单并上传文件
3. 跳转到标注页面

### 方案 3: 使用命令行工具

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "示例数据集"
```

## 📋 数据格式速查

**基本格式（JSONL）：**

```json
{"messages":[{"role":"user","content":"问题"},{"role":"assistant","content":"回答"}]}
```

**带系统提示：**

```json
{"messages":[{"role":"system","content":"系统提示"},{"role":"user","content":"问题"},{"role":"assistant","content":"回答"}]}
```

**多模态（图文）：**

```json
{"messages":[{"role":"user","content":[{"type":"text","text":"描述这张图"},{"type":"image_url","image_url":{"url":"https://example.com/img.jpg"}}]},{"role":"assistant","content":"图片描述..."}]}
```

## 🔧 自定义和集成

### 在您的应用中集成上传功能

**JavaScript 示例：**

```javascript
// 1. 创建数据集
const response = await fetch('http://localhost:8000/api/datasets', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: '我的数据集',
    type: 'sft',
    description: '描述'
  })
});
const dataset = await response.json();

// 2. 上传文件
const formData = new FormData();
formData.append('file', fileObject);

await fetch(`http://localhost:8000/api/datasets/${dataset.id}/upload`, {
  method: 'POST',
  body: formData
});
```

**Python 示例：**

```python
import requests

# 1. 创建数据集
response = requests.post('http://localhost:8000/api/datasets', json={
    'name': '我的数据集',
    'type': 'sft',
    'description': '描述'
})
dataset = response.json()

# 2. 上传文件
with open('data.jsonl', 'rb') as f:
    files = {'file': f}
    requests.post(
        f'http://localhost:8000/api/datasets/{dataset["id"]}/upload',
        files=files
    )
```

**cURL 示例：**

```bash
# 1. 创建数据集
DATASET_ID=$(curl -X POST http://localhost:8000/api/datasets \
  -H "Content-Type: application/json" \
  -d '{"name":"我的数据集","type":"sft"}' | jq -r '.id')

# 2. 上传文件
curl -X POST http://localhost:8000/api/datasets/$DATASET_ID/upload \
  -F "file=@data.jsonl"
```

## 🚀 进阶功能

### 批量上传

如果您有多个数据文件，可以使用脚本批量上传：

```python
import os
from pathlib import Path

data_dir = Path('data/to_upload')
for jsonl_file in data_dir.glob('*.jsonl'):
    # 使用 upload_sft_dataset.py 上传
    os.system(f'python scripts/upload_sft_dataset.py -f {jsonl_file} -n "{jsonl_file.stem}"')
```

### 格式转换

如果您的数据是其他格式（如纯文本对话），可以先转换：

```python
import json

# 示例：将简单问答转换为 SFT 格式
qa_pairs = [
    {"question": "你好", "answer": "你好！有什么可以帮助你的吗？"},
    {"question": "什么是AI", "answer": "AI是人工智能..."}
]

with open('converted.jsonl', 'w', encoding='utf-8') as f:
    for qa in qa_pairs:
        sft_format = {
            "messages": [
                {"role": "user", "content": qa["question"]},
                {"role": "assistant", "content": qa["answer"]}
            ]
        }
        f.write(json.dumps(sft_format, ensure_ascii=False) + '\n')
```

## 🐛 故障排除

### 常见问题

**1. 上传失败：连接被拒绝**

确保后端服务正在运行：
```bash
cd label-app/backend
python run.py
```

**2. 数据格式错误**

使用验证工具检查：
```bash
python scripts/upload_sft_dataset.py --file your_data.jsonl --validate-only
```

**3. CORS 错误**

如果从不同域名访问，需要配置后端 CORS 设置。

**4. 文件过大**

建议将大文件分割成多个小文件：
```bash
split -l 1000 large_file.jsonl smaller_file_
```

## 📞 获取帮助

- 查看完整文档：[SFT数据集上传指南.md](../SFT数据集上传指南.md)
- 参考示例数据：[data/sft_dataset_example.jsonl](../data/sft_dataset_example.jsonl)
- 使用验证工具：`scripts/upload_sft_dataset.py`

## 📝 反馈和贡献

欢迎提交问题报告和改进建议！
