"""
调试向量化器 - 检查为什么会生成 0 特征的向量
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_transformer.analysis.embedding import BM25Vectorizer


def debug_vectorizer(input_file: str, sample_size: int = 10):
    """
    调试向量化器

    Args:
        input_file: 输入文件路径
        sample_size: 采样大小
    """
    print(f"读取文件: {input_file}")

    # 加载数据
    data = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= sample_size:
                break
            data.append(json.loads(line))

    print(f"加载了 {len(data)} 条数据")

    # 准备文本
    texts = []
    for item in data:
        instruction = item.get('instruction', '')
        output = item.get('output', '')
        input_text = item.get('input', '')
        combined = f"{instruction} {input_text} {output}".strip()
        texts.append(combined)

    print(f"\n前3条文本示例:")
    for i, text in enumerate(texts[:3]):
        print(f"\n--- 文本 {i+1} (长度: {len(text)}) ---")
        print(text[:200] + "..." if len(text) > 200 else text)

    # 测试向量化
    print(f"\n开始向量化...")
    vectorizer = BM25Vectorizer(use_jieba=True, max_features=10000, min_df=2)

    print("Fit...")
    vectorizer.fit(texts)

    print(f"词汇表大小: {len(vectorizer.vocabulary)}")
    print(f"前20个词: {list(vectorizer.vocabulary.keys())[:20]}")

    print("\nTransform...")
    embeddings = vectorizer.transform(texts)

    print(f"向量矩阵形状: {embeddings.shape}")
    print(f"非零元素数量: {embeddings.nnz}")

    if embeddings.shape[1] == 0:
        print("\n⚠️ 警告：向量矩阵没有特征！")
        print(f"可能原因：")
        print(f"  - min_df={vectorizer.min_df} 太高")
        print(f"  - max_df={vectorizer.max_df} 太低")
        print(f"  - 文档数量: {len(texts)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="调试向量化器")
    parser.add_argument("--input", "-i", required=True, help="输入文件路径")
    parser.add_argument("--sample-size", "-s", type=int, default=100, help="采样大小")

    args = parser.parse_args()

    debug_vectorizer(args.input, args.sample_size)
