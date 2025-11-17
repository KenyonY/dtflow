"""
可视化模块 - 生成数据分析结果的可视化图表

支持聚类分布、主题词云、质量指标等可视化
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from wordcloud import WordCloud
import logging
from pathlib import Path
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json

logger = logging.getLogger(__name__)


def _find_chinese_font() -> Optional[str]:
    """
    查找系统中可用的中文字体

    Returns:
        字体路径，如果没有找到则返回None
    """
    # 常见的中文字体列表（按优先级排序）
    chinese_fonts = [
        'SimHei',           # 黑体
        'Microsoft YaHei',  # 微软雅黑
        'PingFang SC',      # 苹果苹方
        'Heiti SC',         # 黑体-简
        'STHeiti',          # 华文黑体
        'WenQuanYi Micro Hei',  # 文泉驿微米黑
        'Noto Sans CJK SC', # 思源黑体
        'Arial Unicode MS'  # Arial Unicode（包含中文）
    ]

    # 尝试查找字体
    for font_name in chinese_fonts:
        try:
            font_path = fm.findfont(fm.FontProperties(family=font_name))
            # 验证找到的不是默认字体
            if font_path and 'DejaVu' not in font_path:
                logger.info(f"找到中文字体: {font_name} at {font_path}")
                return font_path
        except Exception:
            continue

    logger.warning("未找到中文字体，将使用系统默认字体（可能无法正确显示中文）")
    return None


# 查找并设置中文字体
_chinese_font_path = _find_chinese_font()
if _chinese_font_path:
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'DejaVu Sans']
else:
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
sns.set_style("whitegrid")


class DataVisualizer:
    """
    数据可视化器

    生成各种分析结果的可视化图表
    """

    def __init__(
        self,
        output_dir: str = "./visualizations",
        interactive: bool = True,
        theme: str = "plotly_white"
    ):
        """
        初始化可视化器

        Args:
            output_dir: 输出目录
            interactive: 是否生成交互式图表
            theme: 图表主题
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interactive = interactive
        self.theme = theme

    def visualize_clustering(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
        topics: Optional[Dict[int, Dict]] = None,
        method: str = 'umap',
        save_path: Optional[str] = None
    ) -> Union[plt.Figure, go.Figure]:
        """
        可视化聚类结果

        Args:
            embeddings: 嵌入向量（高维）
            labels: 聚类标签
            topics: 主题信息
            method: 降维方法 ('umap', 'tsne', 'pca')
            save_path: 保存路径

        Returns:
            图表对象
        """
        logger.info(f"生成聚类可视化，降维方法：{method}")

        # 检查数据量
        if len(embeddings) < 3:
            logger.warning(f"数据量太小({len(embeddings)}条)，跳过聚类可视化")
            return None

        # 降维到2D
        embeddings_2d = self._reduce_dimensions(embeddings, method, n_components=2)

        # 检查降维结果
        if embeddings_2d.shape[1] < 2:
            logger.warning(f"降维后维度不足({embeddings_2d.shape[1]}维)，跳过聚类可视化")
            return None

        if self.interactive:
            return self._create_interactive_cluster_plot(embeddings_2d, labels, topics, save_path)
        else:
            return self._create_static_cluster_plot(embeddings_2d, labels, topics, save_path)

    def _reduce_dimensions(
        self,
        embeddings: np.ndarray,
        method: str,
        n_components: int = 2
    ) -> np.ndarray:
        """
        降维处理

        Args:
            embeddings: 高维嵌入
            method: 降维方法
            n_components: 目标维度

        Returns:
            降维后的嵌入
        """
        if embeddings.shape[1] <= n_components:
            return embeddings

        if method == 'umap':
            try:
                import umap
                reducer = umap.UMAP(n_components=n_components, random_state=42)
                return reducer.fit_transform(embeddings)
            except ImportError:
                logger.warning("UMAP未安装，使用PCA替代")
                method = 'pca'

        if method == 'tsne':
            from sklearn.manifold import TSNE
            reducer = TSNE(n_components=n_components, random_state=42)
            return reducer.fit_transform(embeddings)

        if method == 'pca':
            from sklearn.decomposition import PCA
            reducer = PCA(n_components=n_components, random_state=42)
            return reducer.fit_transform(embeddings)

        raise ValueError(f"不支持的降维方法：{method}")

    def _create_interactive_cluster_plot(
        self,
        embeddings_2d: np.ndarray,
        labels: np.ndarray,
        topics: Optional[Dict[int, Dict]],
        save_path: Optional[str]
    ) -> go.Figure:
        """
        创建交互式聚类图

        Returns:
            Plotly图表对象
        """
        # 准备数据
        unique_labels = np.unique(labels)
        n_clusters = len([l for l in unique_labels if l >= 0])

        # 创建颜色映射
        colors = px.colors.qualitative.Plotly * (n_clusters // 10 + 1)

        # 创建散点图
        fig = go.Figure()

        for label_id in unique_labels:
            mask = labels == label_id
            cluster_points = embeddings_2d[mask]

            # 获取主题信息
            hover_text = f"Cluster {label_id}"
            if topics and label_id in topics:
                topic_info = topics[label_id]
                keywords = [kw[0] for kw in topic_info['keywords'][:5]]
                hover_text = f"Cluster {label_id}<br>Keywords: {', '.join(keywords)}<br>Size: {topic_info['size']}"

            # 添加散点
            fig.add_trace(go.Scatter(
                x=cluster_points[:, 0],
                y=cluster_points[:, 1],
                mode='markers',
                name=f'Cluster {label_id}' if label_id >= 0 else 'Noise',
                marker=dict(
                    size=5,
                    color=colors[label_id % len(colors)] if label_id >= 0 else 'gray',
                    opacity=0.6 if label_id >= 0 else 0.3
                ),
                hovertext=hover_text,
                hoverinfo='text'
            ))

        # 更新布局
        fig.update_layout(
            title="聚类分布可视化",
            xaxis_title="Dimension 1",
            yaxis_title="Dimension 2",
            template=self.theme,
            showlegend=True,
            height=600,
            width=800
        )

        # 保存图表
        if save_path:
            fig.write_html(save_path)
            logger.info(f"交互式聚类图已保存到：{save_path}")

        return fig

    def _create_static_cluster_plot(
        self,
        embeddings_2d: np.ndarray,
        labels: np.ndarray,
        topics: Optional[Dict[int, Dict]],
        save_path: Optional[str]
    ) -> plt.Figure:
        """
        创建静态聚类图

        Returns:
            Matplotlib图表对象
        """
        fig, ax = plt.subplots(1, 1, figsize=(10, 8))

        # 绘制散点图
        scatter = ax.scatter(
            embeddings_2d[:, 0],
            embeddings_2d[:, 1],
            c=labels,
            cmap='tab20',
            alpha=0.6,
            s=10
        )

        # 添加颜色条
        plt.colorbar(scatter, ax=ax, label='Cluster ID')

        # 添加聚类中心标注
        if topics:
            for label_id, topic_info in topics.items():
                cluster_mask = labels == label_id
                if np.any(cluster_mask):
                    center = np.mean(embeddings_2d[cluster_mask], axis=0)
                    keywords = [kw[0] for kw in topic_info['keywords'][:3]]
                    ax.annotate(
                        f"{label_id}: {', '.join(keywords)}",
                        xy=center,
                        fontsize=8,
                        ha='center'
                    )

        ax.set_xlabel("Dimension 1")
        ax.set_ylabel("Dimension 2")
        ax.set_title("聚类分布可视化")

        plt.tight_layout()

        # 保存图表
        if save_path:
            fig.savefig(save_path, dpi=150)
            logger.info(f"静态聚类图已保存到：{save_path}")

        return fig

    def visualize_topics(
        self,
        topics: Dict[int, Dict],
        save_path: Optional[str] = None
    ) -> Union[plt.Figure, go.Figure]:
        """
        可视化主题分布

        Args:
            topics: 主题信息字典
            save_path: 保存路径

        Returns:
            图表对象
        """
        logger.info("生成主题分布可视化")

        if self.interactive:
            return self._create_interactive_topic_plot(topics, save_path)
        else:
            return self._create_static_topic_plot(topics, save_path)

    def _create_interactive_topic_plot(
        self,
        topics: Dict[int, Dict],
        save_path: Optional[str]
    ) -> go.Figure:
        """
        创建交互式主题图

        Returns:
            Plotly图表对象
        """
        # 准备数据
        topic_ids = []
        topic_sizes = []
        topic_labels = []

        for topic_id, topic_info in topics.items():
            topic_ids.append(topic_id)
            topic_sizes.append(topic_info['size'])
            keywords = [kw[0] for kw in topic_info['keywords'][:5]]
            topic_labels.append(f"Topic {topic_id}: {', '.join(keywords)}")

        # 创建条形图
        fig = go.Figure(data=[
            go.Bar(
                x=topic_sizes,
                y=topic_labels,
                orientation='h',
                marker=dict(
                    color=topic_sizes,
                    colorscale='Viridis',
                    showscale=True,
                    colorbar=dict(title="样本数")
                ),
                hovertemplate='%{y}<br>样本数: %{x}<extra></extra>'
            )
        ])

        # 更新布局
        fig.update_layout(
            title="主题分布",
            xaxis_title="样本数量",
            yaxis_title="主题",
            template=self.theme,
            height=max(400, len(topics) * 30),
            margin=dict(l=200)
        )

        # 保存图表
        if save_path:
            fig.write_html(save_path)
            logger.info(f"交互式主题图已保存到：{save_path}")

        return fig

    def _create_static_topic_plot(
        self,
        topics: Dict[int, Dict],
        save_path: Optional[str]
    ) -> plt.Figure:
        """
        创建静态主题图

        Returns:
            Matplotlib图表对象
        """
        # 准备数据
        topic_ids = []
        topic_sizes = []
        topic_labels = []

        for topic_id, topic_info in topics.items():
            topic_ids.append(topic_id)
            topic_sizes.append(topic_info['size'])
            keywords = [kw[0] for kw in topic_info['keywords'][:3]]
            topic_labels.append(f"T{topic_id}: {', '.join(keywords)}")

        # 创建图表
        fig, ax = plt.subplots(1, 1, figsize=(10, max(6, len(topics) * 0.3)))

        # 绘制水平条形图
        bars = ax.barh(topic_labels, topic_sizes, color=plt.cm.Viridis(np.linspace(0, 1, len(topics))))

        # 添加数值标签
        for bar, size in zip(bars, topic_sizes):
            ax.text(bar.get_width(), bar.get_y() + bar.get_height()/2,
                   f'{size}', ha='left', va='center')

        ax.set_xlabel("样本数量")
        ax.set_ylabel("主题")
        ax.set_title("主题分布")

        plt.tight_layout()

        # 保存图表
        if save_path:
            fig.savefig(save_path, dpi=150)
            logger.info(f"静态主题图已保存到：{save_path}")

        return fig

    def create_word_cloud(
        self,
        text_data: Union[List[str], Dict[str, float]],
        save_path: Optional[str] = None
    ) -> plt.Figure:
        """
        创建词云图

        Args:
            text_data: 文本列表或词频字典
            save_path: 保存路径

        Returns:
            图表对象
        """
        logger.info("生成词云图")

        # 处理输入数据
        # 使用自动查找的中文字体，如果没有找到则使用None（系统默认）
        wordcloud_kwargs = {
            'width': 800,
            'height': 400,
            'background_color': 'white',
            'max_words': 100
        }
        if _chinese_font_path:
            wordcloud_kwargs['font_path'] = _chinese_font_path

        if isinstance(text_data, list):
            text = ' '.join(text_data)
            wordcloud = WordCloud(**wordcloud_kwargs).generate(text)
        else:
            wordcloud = WordCloud(**wordcloud_kwargs).generate_from_frequencies(text_data)

        # 创建图表
        fig, ax = plt.subplots(1, 1, figsize=(12, 6))
        ax.imshow(wordcloud, interpolation='bilinear')
        ax.axis('off')
        ax.set_title("关键词云图")

        plt.tight_layout()

        # 保存图表
        if save_path:
            fig.savefig(save_path, dpi=150)
            logger.info(f"词云图已保存到：{save_path}")

        return fig

    def visualize_quality_metrics(
        self,
        quality_metrics: Dict[str, Any],
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        可视化质量指标

        Args:
            quality_metrics: 质量评估结果
            save_path: 保存路径

        Returns:
            图表对象
        """
        logger.info("生成质量指标可视化")

        # 创建子图
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "长度分布",
                "多样性指标",
                "重复率统计",
                "总体质量评分"
            ),
            specs=[[{"type": "box"}, {"type": "bar"}],
                  [{"type": "bar"}, {"type": "indicator"}]]
        )

        # 1. 长度分布箱线图
        length_data = quality_metrics.get('length_stats', {})
        fig.add_trace(
            go.Box(
                y=[length_data.get('instruction_mean', 0),
                   length_data.get('output_mean', 0),
                   length_data.get('total_mean', 0)],
                x=['指令长度', '输出长度', '总长度'],
                name="长度分布"
            ),
            row=1, col=1
        )

        # 2. 多样性指标条形图
        diversity_data = quality_metrics.get('diversity_scores', {})
        fig.add_trace(
            go.Bar(
                x=list(diversity_data.keys()),
                y=list(diversity_data.values()),
                name="多样性分数",
                marker_color='lightgreen'
            ),
            row=1, col=2
        )

        # 3. 重复率统计
        dup_data = quality_metrics.get('duplication_stats', {})
        fig.add_trace(
            go.Bar(
                x=list(dup_data.keys()),
                y=list(dup_data.values()),
                name="重复率",
                marker_color='coral'
            ),
            row=2, col=1
        )

        # 4. 总体质量评分仪表盘
        overall_score = quality_metrics.get('overall_score', 0)
        fig.add_trace(
            go.Indicator(
                mode="gauge+number+delta",
                value=overall_score,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "总体质量分数"},
                delta={'reference': 80},
                gauge={
                    'axis': {'range': [None, 100]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, 50], 'color': "lightgray"},
                        {'range': [50, 80], 'color': "gray"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 90
                    }
                }
            ),
            row=2, col=2
        )

        # 更新布局
        fig.update_layout(
            title="数据集质量评估报告",
            template=self.theme,
            showlegend=False,
            height=700
        )

        # 保存图表
        if save_path:
            fig.write_html(save_path)
            logger.info(f"质量指标图已保存到：{save_path}")

        return fig

    def generate_analysis_report(
        self,
        analysis_results: Dict[str, Any],
        save_path: str = "analysis_report.html"
    ) -> str:
        """
        生成综合分析报告

        Args:
            analysis_results: 完整的分析结果
            save_path: 保存路径

        Returns:
            报告文件路径
        """
        logger.info("生成综合分析报告")

        # HTML模板
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>SFT数据集分析报告</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; border-bottom: 2px solid #eee; padding-bottom: 5px; }}
                .metric {{ display: inline-block; margin: 10px; padding: 10px;
                          background: #f5f5f5; border-radius: 5px; }}
                .warning {{ color: #ff9800; }}
                .recommendation {{ color: #4CAF50; }}
                .chart-container {{ margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>SFT数据集分析报告</h1>

            <h2>1. 数据集概览</h2>
            <div class="metrics">
                <div class="metric">样本总数: {n_samples}</div>
                <div class="metric">聚类数: {n_clusters}</div>
                <div class="metric">总体质量分数: {overall_score:.1f}/100</div>
            </div>

            <h2>2. 质量评估</h2>
            {quality_section}

            <h2>3. 聚类分析</h2>
            {clustering_section}

            <h2>4. 主题分析</h2>
            {topic_section}

            <h2>5. 警告与建议</h2>
            <div class="warnings">
                <h3>质量警告</h3>
                <ul>
                {warnings}
                </ul>
            </div>

            <div class="recommendations">
                <h3>改进建议</h3>
                <ul>
                {recommendations}
                </ul>
            </div>

            <h2>6. 可视化图表</h2>
            {charts_section}

            <hr>
            <p style="text-align: center; color: #999;">
                报告生成时间: {timestamp}
            </p>
        </body>
        </html>
        """

        # 填充模板
        import datetime

        # 提取关键信息
        n_samples = analysis_results.get('n_samples', 0)
        n_clusters = analysis_results.get('clustering', {}).get('n_clusters', 0)
        overall_score = analysis_results.get('quality', {}).get('overall_score', 0)

        # 生成各个部分的HTML
        quality_section = self._format_quality_section(analysis_results.get('quality', {}))
        clustering_section = self._format_clustering_section(analysis_results.get('clustering', {}))
        topic_section = self._format_topic_section(analysis_results.get('topics', {}))

        # 格式化警告和建议
        warnings = analysis_results.get('quality', {}).get('warnings', [])
        warnings_html = '\n'.join([f'<li class="warning">{w}</li>' for w in warnings])

        recommendations = analysis_results.get('quality', {}).get('recommendations', [])
        recommendations_html = '\n'.join([f'<li class="recommendation">{r}</li>' for r in recommendations])

        # 生成图表链接
        charts_section = '<div class="chart-container">请查看生成的可视化文件</div>'

        # 填充HTML
        html_content = html_template.format(
            n_samples=n_samples,
            n_clusters=n_clusters,
            overall_score=overall_score,
            quality_section=quality_section,
            clustering_section=clustering_section,
            topic_section=topic_section,
            warnings=warnings_html,
            recommendations=recommendations_html,
            charts_section=charts_section,
            timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        # 保存报告
        report_path = self.output_dir / save_path
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"分析报告已保存到：{report_path}")
        return str(report_path)

    def _format_quality_section(self, quality_data: Dict) -> str:
        """格式化质量部分的HTML"""
        if not quality_data:
            return "<p>无质量数据</p>"

        html = "<table border='1' style='border-collapse: collapse;'>"
        html += "<tr><th>指标</th><th>数值</th></tr>"

        for key, value in quality_data.items():
            if isinstance(value, dict):
                continue
            if isinstance(value, float):
                html += f"<tr><td>{key}</td><td>{value:.4f}</td></tr>"
            else:
                html += f"<tr><td>{key}</td><td>{value}</td></tr>"

        html += "</table>"
        return html

    def _format_clustering_section(self, clustering_data: Dict) -> str:
        """格式化聚类部分的HTML"""
        if not clustering_data:
            return "<p>无聚类数据</p>"

        html = f"<p>聚类算法: {clustering_data.get('algorithm', 'Unknown')}</p>"
        html += f"<p>聚类数量: {clustering_data.get('n_clusters', 0)}</p>"

        if 'scores' in clustering_data:
            html += "<h4>聚类评估指标:</h4><ul>"
            for metric, score in clustering_data['scores'].items():
                html += f"<li>{metric}: {score:.4f}</li>"
            html += "</ul>"

        return html

    def _format_topic_section(self, topics_data: Dict) -> str:
        """格式化主题部分的HTML"""
        if not topics_data:
            return "<p>无主题数据</p>"

        html = "<h4>主要主题:</h4>"
        html += "<ul>"

        for topic_id, topic_info in list(topics_data.items())[:10]:
            keywords = [kw[0] for kw in topic_info.get('keywords', [])[:5]]
            size = topic_info.get('size', 0)
            html += f"<li>主题{topic_id} (样本数:{size}): {', '.join(keywords)}</li>"

        html += "</ul>"
        return html