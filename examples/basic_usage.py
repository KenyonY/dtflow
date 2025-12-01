"""
DataTransformer 基本使用示例

本示例演示如何加载、处理和保存通用格式的数据。
"""

from data_transformer import DataTransformer

def main():
    print("=" * 60)
    print("DataTransformer 基本使用示例")
    print("=" * 60)

    # 1. 加载数据
    print("\n1. 加载数据")
    print("-" * 40)
    dt = DataTransformer.load("data/data.jsonl")
    print(f"✓ 成功加载 {len(dt)} 条数据")
    print(f"  第一条: {dt[0]}")

    # 2. 查看统计信息
    print("\n2. 数据统计")
    print("-" * 40)
    stats = dt.stats()
    print(f"  总数: {stats['total']}")
    print(f"  字段: {', '.join(stats['fields'])}")

    # 按语言统计
    zh_count = dt.count(lambda x: x.get('language') == 'zh')
    en_count = dt.count(lambda x: x.get('language') == 'en')
    print(f"  中文数据: {zh_count} 条")
    print(f"  英文数据: {en_count} 条")

    # 3. 数据过滤
    print("\n3. 数据过滤 (score > 0.85)")
    print("-" * 40)
    dt_filtered = dt.copy().filter(lambda x: x.get('score', 0) > 0.85)
    print(f"  过滤前: {len(dt)} 条")
    print(f"  过滤后: {len(dt_filtered)} 条")

    # 4. 数据转换
    print("\n4. 数据转换 (添加处理标记)")
    print("-" * 40)
    dt_transformed = dt.copy().map(
        lambda x: {**x, 'processed': True, 'version': '1.0'}
    )
    print(f"  转换后第一条: {dt_transformed[0]}")

    # 5. 链式操作
    print("\n5. 链式操作示例")
    print("-" * 40)
    result = (DataTransformer.load("data/data.jsonl")
              .filter(lambda x: x.get('score', 0) > 0.85)
              .map(lambda x: {**x, 'high_quality': True})
              .shuffle(seed=42))
    print(f"  最终结果: {len(result)} 条高质量数据")

    # 6. 数据分割
    print("\n6. 数据分割 (80/20)")
    print("-" * 40)
    train, test = dt.split(ratio=0.8, shuffle=True, seed=42)
    print(f"  训练集: {len(train)} 条")
    print(f"  测试集: {len(test)} 条")

    # 7. 保存数据
    print("\n7. 保存处理后的数据")
    print("-" * 40)
    dt_filtered.save("data/output.jsonl")
    print(f"  ✓ 已保存到 data/output.jsonl")

    # 8. 相似度计算
    print("\n8. 相似度计算")
    print("-" * 40)
    if len(dt) >= 2:
        similarity = dt.similarity(0, 1, method='cosine', text_field='text')
        print(f"  第0条和第1条的相似度: {similarity:.4f}")

        # 查找相似项
        similar_items = dt.find_similar(reference=0, top_k=3, text_field='text')
        print(f"  与第0条最相似的3条:")
        for idx, score in similar_items:
            print(f"    - 索引 {idx}: {score:.4f}")

    print("\n" + "=" * 60)
    print("示例运行完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
