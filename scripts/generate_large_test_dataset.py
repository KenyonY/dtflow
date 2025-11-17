#!/usr/bin/env python3
"""
生成大规模SFT测试数据集

用于性能测试和验证
"""

import json
import random
from pathlib import Path


# 定义不同主题的问答对模板
TOPICS = {
    "机器学习": [
        ("什么是{concept}？", "{concept}是机器学习中的一个重要概念，它{description}。"),
        ("{concept}的原理是什么？", "{concept}的核心原理是{description}，通过{method}来实现。"),
        ("如何理解{concept}？", "理解{concept}需要掌握{description}，它在{application}中应用广泛。"),
        ("解释一下{concept}", "{concept}是{description}，主要用于{application}场景。"),
        ("{concept}有什么优缺点？", "{concept}的优点是{advantage}，缺点是{disadvantage}。"),
    ],
    "深度学习": [
        ("{model}模型是什么？", "{model}是一种深度学习模型，{description}。"),
        ("{model}的架构特点", "{model}的主要特点是{feature}，擅长处理{task}任务。"),
        ("如何训练{model}？", "训练{model}需要{requirement}，使用{method}优化。"),
        ("{model}适用于什么场景？", "{model}特别适合{scenario}，在{application}中表现出色。"),
        ("{model}与{other}的区别", "{model}相比{other}，主要区别在于{difference}。"),
    ],
    "Python编程": [
        ("Python中如何{operation}？", "在Python中，使用{code}可以实现{operation}。"),
        ("{feature}的用法是什么？", "{feature}是Python的{description}，语法为{syntax}。"),
        ("解释Python的{concept}", "Python的{concept}是{description}，例如{example}。"),
        ("{library}库怎么用？", "{library}是用于{purpose}的库，基本用法：{usage}。"),
        ("Python {operation}最佳实践", "进行{operation}时，推荐{best_practice}，避免{anti_pattern}。"),
    ],
    "数据科学": [
        ("如何进行{analysis}？", "{analysis}的步骤包括{steps}，使用{tools}工具。"),
        ("{metric}指标的含义", "{metric}用于评估{purpose}，计算方式为{formula}。"),
        ("数据{preprocessing}的方法", "常见的{preprocessing}方法有{methods}，选择时考虑{factors}。"),
        ("{technique}技术的应用", "{technique}主要应用于{scenario}，能够{benefit}。"),
        ("如何选择{algorithm}？", "选择{algorithm}需要考虑{factors}，在{condition}情况下使用。"),
    ],
    "Web开发": [
        ("{framework}框架如何使用？", "{framework}是{description}，基本使用方法：{usage}。"),
        ("如何实现{feature}？", "实现{feature}可以使用{technology}，代码示例：{example}。"),
        ("{concept}是什么意思？", "在Web开发中，{concept}指的是{description}，用于{purpose}。"),
        ("解释{pattern}设计模式", "{pattern}模式{description}，适用于{scenario}场景。"),
        ("{tool}的作用是什么？", "{tool}用于{purpose}，主要功能包括{features}。"),
    ],
}

# 填充词库
FILLERS = {
    "机器学习": {
        "concept": ["监督学习", "无监督学习", "强化学习", "过拟合", "欠拟合", "正则化",
                   "交叉验证", "特征工程", "集成学习", "降维", "梯度下降", "损失函数"],
        "description": ["通过数据学习模式", "使用标注数据训练", "最小化预测误差",
                       "提取数据特征", "组合多个模型", "减少特征维度"],
        "method": ["迭代优化", "反向传播", "随机梯度下降", "批量训练"],
        "application": ["图像识别", "自然语言处理", "推荐系统", "异常检测"],
        "advantage": ["准确率高", "自动学习特征", "可扩展性强"],
        "disadvantage": ["需要大量数据", "计算成本高", "模型解释性差"],
    },
    "深度学习": {
        "model": ["CNN", "RNN", "LSTM", "Transformer", "GAN", "ResNet", "BERT", "GPT"],
        "description": ["使用多层神经网络", "捕捉序列信息", "注意力机制"],
        "feature": ["多层卷积结构", "循环连接", "自注意力机制", "残差连接"],
        "task": ["图像分类", "目标检测", "序列标注", "文本生成"],
        "requirement": ["大量标注数据", "GPU加速", "充足的训练时间"],
        "scenario": ["计算机视觉", "语音识别", "机器翻译", "对话系统"],
        "other": ["传统方法", "CNN", "RNN", "MLP"],
        "difference": ["模型结构", "参数量", "训练方式", "适用场景"],
    },
    "Python编程": {
        "operation": ["读取文件", "列表推导", "异常处理", "装饰器", "生成器"],
        "code": ["with open('file.txt')", "[x for x in range(10)]", "try-except"],
        "feature": ["列表推导式", "生成器表达式", "装饰器", "上下文管理器"],
        "description": ["简洁的语法糖", "惰性求值机制", "函数包装器"],
        "syntax": ["[expr for item in iterable]", "@decorator", "with ... as ..."],
        "concept": ["闭包", "迭代器", "生成器", "元类", "描述符"],
        "example": ["lambda x: x**2", "yield返回值", "装饰器嵌套"],
        "library": ["numpy", "pandas", "requests", "matplotlib", "scikit-learn"],
        "purpose": ["数值计算", "数据处理", "HTTP请求", "数据可视化"],
        "usage": ["import numpy as np", "df.groupby('col')", "requests.get(url)"],
        "best_practice": ["使用上下文管理器", "类型注解", "列表推导式"],
        "anti_pattern": ["裸except", "可变默认参数", "全局变量"],
    },
    "数据科学": {
        "analysis": ["探索性数据分析", "特征选择", "模型评估", "A/B测试"],
        "steps": ["数据收集、清洗、转换、建模", "假设检验、可视化、结论"],
        "tools": ["pandas、matplotlib", "scikit-learn", "statsmodels"],
        "metric": ["准确率", "召回率", "F1分数", "AUC", "RMSE"],
        "purpose": ["分类性能", "回归效果", "模型泛化能力"],
        "formula": ["TP/(TP+FP)", "预测值与真实值的均方根误差"],
        "preprocessing": ["缺失值处理", "异常值检测", "特征标准化", "编码"],
        "methods": ["删除、填充、插值", "归一化、标准化", "独热编码"],
        "factors": ["数据分布", "业务需求", "计算成本"],
        "technique": ["主成分分析", "聚类分析", "时间序列分析"],
        "scenario": ["降维可视化", "用户分组", "趋势预测"],
        "benefit": ["减少特征维度", "发现数据模式", "提高预测准确性"],
        "algorithm": ["分类算法", "回归算法", "聚类算法"],
        "condition": ["数据量大、维度高", "标签明确", "需要解释性"],
    },
    "Web开发": {
        "framework": ["React", "Vue", "Django", "Flask", "Express"],
        "description": ["前端UI框架", "轻量级Web框架", "全栈框架"],
        "usage": ["创建组件、状态管理", "定义路由、处理请求"],
        "feature": ["用户认证", "文件上传", "实时通信", "API接口"],
        "technology": ["JWT令牌", "FormData", "WebSocket", "RESTful"],
        "example": ["app.post('/upload', handler)", "socket.emit('message')"],
        "concept": ["MVC模式", "前后端分离", "RESTful API", "中间件"],
        "purpose": ["代码解耦", "提高可维护性", "统一接口规范"],
        "pattern": ["单例", "工厂", "观察者", "装饰器"],
        "tool": ["Webpack", "Babel", "ESLint", "Docker"],
        "features": ["模块打包、代码分割", "代码转译", "代码检查"],
    },
}


def generate_qa_pair(topic: str) -> dict:
    """生成一个问答对"""
    templates = TOPICS[topic]
    fillers = FILLERS[topic]

    # 随机选择一个模板
    q_template, a_template = random.choice(templates)

    # 填充模板
    fill_values = {}
    for key in fillers:
        if f"{{{key}}}" in q_template or f"{{{key}}}" in a_template:
            fill_values[key] = random.choice(fillers[key])

    try:
        question = q_template.format(**fill_values)
        answer = a_template.format(**fill_values)
    except KeyError:
        # 如果缺少某些键，使用默认值
        question = q_template
        answer = a_template

    return {
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer}
        ]
    }


def generate_dataset(n_samples: int = 500, output_file: str = None) -> list:
    """
    生成测试数据集

    Args:
        n_samples: 样本数量
        output_file: 输出文件路径

    Returns:
        数据列表
    """
    data = []
    topics = list(TOPICS.keys())

    # 为每个主题生成数据
    samples_per_topic = n_samples // len(topics)

    for topic in topics:
        for _ in range(samples_per_topic):
            data.append(generate_qa_pair(topic))

    # 补充剩余的样本
    remaining = n_samples - len(data)
    for _ in range(remaining):
        topic = random.choice(topics)
        data.append(generate_qa_pair(topic))

    # 打乱数据
    random.shuffle(data)

    # 保存到文件
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')

        print(f"✓ 已生成 {len(data)} 条数据到 {output_file}")

    return data


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成大规模SFT测试数据集")
    parser.add_argument("-n", "--num-samples", type=int, default=500,
                       help="样本数量（默认: 500）")
    parser.add_argument("-o", "--output", type=str,
                       default="tests/test_data/large_sft_test.jsonl",
                       help="输出文件路径")

    args = parser.parse_args()

    generate_dataset(args.num_samples, args.output)
