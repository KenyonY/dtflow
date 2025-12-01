#!/usr/bin/env python3
"""
测试LLM主题命名功能

简单脚本用于测试Ollama服务连接和LLM主题命名功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_transformer.analysis.llm_topic_namer import OllamaClient, LLMTopicNamer


def test_ollama_connection():
    """测试Ollama服务连接"""
    print("="*60)
    print("测试1: Ollama服务连接")
    print("="*60)

    client = OllamaClient("http://localhost:11434")

    try:
        # 测试生成API
        print("\n测试生成API...")
        response = client.generate(
            model="gemma3:4b",
            prompt="Say hello in Chinese",
            temperature=0.7
        )
        print(f"✓ 生成API正常")
        print(f"响应: {response[:100]}...")

        # 测试Embedding API
        print("\n测试Embedding API...")
        embedding = client.embeddings(
            model="bge-m3:latest",
            text="这是一个测试文本"
        )
        print(f"✓ Embedding API正常")
        print(f"向量维度: {len(embedding)}")

        return True

    except Exception as e:
        print(f"✗ 连接失败: {e}")
        print("\n请检查:")
        print("1. Ollama服务是否启动: ollama serve")
        print("2. 模型是否已下载:")
        print("   ollama pull gemma3:4b")
        print("   ollama pull bge-m3:latest")
        return False


def test_topic_naming():
    """测试主题命名功能"""
    print("\n" + "="*60)
    print("测试2: LLM主题命名")
    print("="*60)

    # 模拟主题数据
    topics = {
        0: {
            'keywords': [
                ('Python', 0.8),
                ('编程', 0.7),
                ('函数', 0.6),
                ('代码', 0.5),
                ('调试', 0.4)
            ],
            'size': 100,
            'sample_docs': [
                "如何使用Python编写一个函数来计算斐波那契数列?",
                "Python中如何进行异常处理和错误调试?",
                "请解释Python装饰器的工作原理"
            ],
            'sample_indices': [0, 1, 2],
            'topic_summary': 'Python / 编程 / 函数 / 代码 / 调试'
        }
    }

    try:
        namer = LLMTopicNamer(
            model="gemma3:4b",
            base_url="http://localhost:11434"
        )

        print("\n生成主题名称...")
        enhanced_topics = namer.generate_topic_names(topics)

        print("\n✓ 主题命名完成")
        print("\n主题详情:")
        for topic_id, topic_info in enhanced_topics.items():
            print(f"\n主题 {topic_id}:")
            print(f"  原始关键词: {', '.join([kw[0] for kw in topic_info['keywords'][:5]])}")
            print(f"  LLM主题名称: {topic_info.get('llm_topic_name', 'N/A')}")
            print(f"  LLM主题描述: {topic_info.get('llm_topic_description', 'N/A')}")

        return True

    except Exception as e:
        print(f"✗ 主题命名失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*60)
    print("LLM主题命名功能测试")
    print("="*60)

    # 测试Ollama连接
    if not test_ollama_connection():
        sys.exit(1)

    # 测试主题命名
    if not test_topic_naming():
        sys.exit(1)

    print("\n" + "="*60)
    print("✓ 所有测试通过!")
    print("="*60)
    print("\n可以开始使用以下命令进行完整分析:")
    print("python scripts/analyze_with_llm.py --input data/sample_10k.jsonl --output analysis_results_llm")


if __name__ == '__main__':
    main()
