"""
简化版测试脚本,用于验证示例数据集和核心功能
避免Windows控制台编码问题
"""

from datatron import DataTransformer


def test_basic_usage():
    """测试基本功能"""
    print("=" * 60)
    print("测试 1: 基本数据加载和处理")
    print("=" * 60)

    # 加载数据
    dt = DataTransformer.load("data/data.jsonl")
    print(f"加载数据: {len(dt)} 条")

    # 统计
    stats = dt.stats()
    print(f"字段: {stats['fields']}")

    # 过滤
    dt_filtered = dt.copy().filter(lambda x: x.get('score', 0) > 0.85)
    print(f"过滤后: {len(dt_filtered)} 条 (score > 0.85)")

    # 分割
    train, test = dt.split(ratio=0.8, shuffle=True, seed=42)
    print(f"训练集: {len(train)} 条, 测试集: {len(test)} 条")

    # 保存
    dt_filtered.save("data/output_test.jsonl")
    print("保存成功: data/output_test.jsonl")

    print("[OK] 基本功能测试通过\n")


def test_sft_data():
    """测试SFT数据加载"""
    print("=" * 60)
    print("测试 2: SFT 数据加载")
    print("=" * 60)

    # 加载SFT数据
    dt = DataTransformer.load("data/sft_data.jsonl")
    print(f"加载SFT数据: {len(dt)} 条")

    # 检查字段
    first_item = dt[0]
    print(f"字段: {list(first_item.keys())}")
    print(f"第一条指令: {first_item['instruction'][:50]}...")

    # 转换为SFT格式
    dt_sft = dt.to_sft()
    print(f"转换为SFT格式: {len(dt_sft)} 条")

    print("[OK] SFT数据测试通过\n")


def main():
    """运行所有测试"""
    print("\n开始测试示例脚本...\n")

    try:
        test_basic_usage()
    except Exception as e:
        print(f"[ERROR] 基本功能测试失败: {e}\n")

    try:
        test_sft_data()
    except Exception as e:
        print(f"[ERROR] SFT数据测试失败: {e}\n")

    print("=" * 60)
    print("所有测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
