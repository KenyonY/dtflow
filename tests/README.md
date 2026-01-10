# 测试说明

## 运行测试

```bash
# 运行全部测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_transformer.py -v

# 运行特定测试
pytest tests/test_transformer.py::TestDataTransformer::test_to_transform -v
```

## 性能测试

### 1. pytest 方式（生成数据测试）

```bash
# 运行全部性能测试
pytest tests/test_cli_benchmark.py -v

# 按类别运行
pytest tests/test_cli_benchmark.py -v -k "sample"     # 采样测试
pytest tests/test_cli_benchmark.py -v -k "random"     # 随机采样
pytest tests/test_cli_benchmark.py -v -k "tail"       # tail 采样
pytest tests/test_cli_benchmark.py -v -k "stats"      # 统计测试
pytest tests/test_cli_benchmark.py -v -k "token"      # Token 统计
pytest tests/test_cli_benchmark.py -v -k "clean"      # 清洗测试
pytest tests/test_cli_benchmark.py -v -k "dedupe"     # 去重测试
pytest tests/test_cli_benchmark.py -v -k "validate"   # 验证测试
pytest tests/test_cli_benchmark.py -v -k "concat"     # 合并测试
pytest tests/test_cli_benchmark.py -v -k "transform"  # 转换测试

# 查看耗时详情
pytest tests/test_cli_benchmark.py -v --durations=0
```

### 2. 真实数据测试（生成报告）

使用 `data/sharegpt_all.json` 进行真实数据性能测试：

```bash
python tests/benchmark_sharegpt.py
```

报告输出到 `benchmark_report.txt`，包含：
- 各命令耗时
- 吞吐量（条/秒）
- 最快/最慢操作排名

### 3. pytest-benchmark（可选）

```bash
pip install pytest-benchmark
pytest tests/test_cli_benchmark.py --benchmark-only --benchmark-sort=mean
```

## 测试覆盖

| 模块 | 测试文件 | 说明 |
|------|----------|------|
| core | test_transformer.py | DataTransformer 核心功能 |
| streaming | test_streaming.py | 流式处理 |
| io | test_io.py | 文件读写 |
| presets | test_transformer.py | 预设转换函数 |
| tokenizers | test_tokenizers.py | Token 统计 |
| converters | test_converters.py | 格式转换器 |
| schema | test_schema.py | 数据验证 |
| field_path | test_field_path.py | 字段路径解析 |
| lineage | test_lineage.py | 数据血缘 |
| pipeline | test_pipeline.py | Pipeline 执行 |
| CLI | test_cli_benchmark.py | CLI 命令性能 |

## 性能测试覆盖

| 命令 | 测试场景 |
|------|----------|
| sample/head/tail | 小/中/大数据集，random/stratified |
| stats | 快速模式，完整模式 |
| token-stats | messages 格式，text 字段 |
| validate | openai_chat，sharegpt |
| clean | strip，drop-empty，min-len，keep |
| dedupe | 全量去重，按字段去重 |
| concat | 多文件合并 |
| diff | 文件对比 |
| transform | 预设转换 |
