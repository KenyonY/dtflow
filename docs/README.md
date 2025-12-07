# DataTransformer 文档

欢迎来到 DataTransformer 项目文档！

## 📚 文档目录树

### 快速开始
- [5分钟快速开始](../QUICKSTART.md) ⭐ - 最快上手方式，推荐新手阅读
- [零门槛使用指南](lowering_barrier_guide.md) - 面向非技术用户的完整教程

### 使用指南 (guides/)
- [SFT 数据集上传指南](guides/sft-upload-guide.md) - 详细的 SFT 格式数据上传教程
- [MLLM 客户端快速开始](guides/mllm-quickstart.md) - 多模态大语言模型客户端使用指南

### 技术报告
- [性能测试报告](performance_test_report.md) - 大规模数据集性能基准测试
- [分析模块测试报告](analysis_module_test_report.md) - 数据分析功能测试
- [SFT 数据集分析](sft_dataset_analysis.md) - SFT 数据集分析示例

### API 文档 (api/)
- [核心 API](api/core.md) - DataTransformer 核心类 API 参考
- [格式转换器](api/formats.md) - SFT、RLHF、Pretrain 格式转换器 API
- [存储后端](api/storage.md) - FlaxKV2 存储管理器 API

### 架构文档 (architecture/)
- [FlaxKV2 存储架构](architecture/flaxkv2.md) - FlaxKV2 集成和设计说明
- [设计原则](architecture/design-principles.md) - 项目设计原则和最佳实践
- [项目结构](architecture/project-structure.md) - 代码组织和模块说明

## 🚀 快速开始

### 安装

```bash
# 安装核心库
pip install -e .

# 安装完整依赖
pip install -e ".[full]"
```

### 基本使用

```python
from datatron import DataTransformer

# 加载数据
dt = DataTransformer.load("data.jsonl")

# 格式转换
sft_data = dt.to_sft(style="messages")

# 保存
dt.save("output.jsonl", format_type="sft")
```

详细使用方法请参考[使用指南](guides/)。

## 🔗 相关链接

- [项目主页](../README.md)
- [贡献指南](../CONTRIBUTING.md)
- [变更日志](../CHANGELOG.md)
- [在线 API 文档](http://localhost:8000/docs) (启动后端服务后访问)

## 📖 文档维护

### 文档组织原则

1. **一个模块一个文档** - 避免文档爆炸
2. **保持主文档简洁** - 详细内容放在子文档中
3. **文档目录树必须更新** - 添加新文档后更新本文件

### 添加新文档

当添加新文档时，请：
1. 将文档放在合适的子目录（guides/、api/、architecture/）
2. 更新本文件的文档目录树
3. 在相关文档中添加交叉引用

## 💡 获取帮助

- 📝 查看 [示例代码](../examples/)
- 🐛 报告问题请访问 [GitHub Issues](https://github.com/yourusername/DataTransformer/issues)
- 💬 加入讨论请访问 [Discussions](https://github.com/yourusername/DataTransformer/discussions)
