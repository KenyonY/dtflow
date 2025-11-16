# DataTransformer

一个专业的数据标注和转换平台，支持 SFT（Supervised Fine-Tuning）和 DPO（Direct Preference Optimization）等多种格式，集成 FlaxKV2 存储后端。

## 快速开始

### SFT 数据集上传

我们提供了多种方式上传和管理 SFT 数据集：

1. **Web 界面** - 使用主应用的可视化界面
2. **独立示例页面** - 查看 [examples/sft_upload_demo.html](examples/sft_upload_demo.html)
3. **命令行工具** - 使用 [scripts/upload_sft_dataset.py](scripts/upload_sft_dataset.py)

详细说明请查看：
- 📖 [SFT 数据集上传指南](docs/guides/sft-upload-guide.md) - 完整的格式说明和使用教程
- 📝 [示例数据文件](data/sft_dataset_example.jsonl) - 标准格式示例
- 🛠️ [工具脚本说明](scripts/README.md) - 命令行工具使用方法
- 💡 [示例代码](examples/README.md) - 各种集成示例
- 📚 [完整文档](docs/README.md) - 查看所有文档

### 快速上传数据

```bash
# 使用命令行工具
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集"

# 或访问 Web 界面
# http://localhost:5173/datasets
```

## 设计原则

1. 组合大于继承: 永远尽可能少的使用继承
2. KISS原则: Keep it simple, stupid

