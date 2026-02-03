"""eval 模块测试"""

import json
import os
import tempfile

# ============ text_parser 测试 ============


class TestStripThinkTags:
    def test_basic(self):
        from dtflow.utils.text_parser import strip_think_tags

        assert strip_think_tags("<think>思考中...</think>答案是42") == "答案是42"

    def test_multiline(self):
        from dtflow.utils.text_parser import strip_think_tags

        text = "<think>\n第一行\n第二行\n</think>\n结果"
        assert strip_think_tags(text) == "结果"

    def test_multiple_tags(self):
        from dtflow.utils.text_parser import strip_think_tags

        text = "<think>a</think>中间<think>b</think>结尾"
        assert strip_think_tags(text) == "中间结尾"

    def test_empty(self):
        from dtflow.utils.text_parser import strip_think_tags

        assert strip_think_tags("") == ""
        assert strip_think_tags(None) is None

    def test_no_tags(self):
        from dtflow.utils.text_parser import strip_think_tags

        assert strip_think_tags("普通文本") == "普通文本"


class TestExtractCodeSnippets:
    def test_basic(self):
        from dtflow.utils.text_parser import extract_code_snippets

        text = '```json\n{"key": "value"}\n```'
        result = extract_code_snippets(text)
        assert len(result) == 1
        assert result[0]["language"] == "json"
        assert result[0]["code"] == '{"key": "value"}'

    def test_no_language(self):
        from dtflow.utils.text_parser import extract_code_snippets

        text = "```\nhello\n```"
        result = extract_code_snippets(text)
        assert len(result) == 1
        assert result[0]["language"] == "unknown"
        assert result[0]["code"] == "hello"

    def test_multiple_blocks(self):
        from dtflow.utils.text_parser import extract_code_snippets

        text = "```python\na=1\n```\n文字\n```json\n{}\n```"
        result = extract_code_snippets(text)
        assert len(result) == 2

    def test_no_blocks(self):
        from dtflow.utils.text_parser import extract_code_snippets

        assert extract_code_snippets("普通文本") == []

    def test_non_strict_brace(self):
        from dtflow.utils.text_parser import extract_code_snippets

        text = '前缀 {"a": 1} 后缀'
        result = extract_code_snippets(text, strict=False)
        assert len(result) == 1
        assert '{"a": 1}' in result[0]["code"]


class TestParseGenericTags:
    def test_closed_tags(self):
        from dtflow.utils.text_parser import parse_generic_tags

        result = parse_generic_tags("<标签>内容</标签>")
        assert result == {"标签": "内容"}

    def test_strict_mode(self):
        from dtflow.utils.text_parser import parse_generic_tags

        result = parse_generic_tags("<a>hello<b>world", strict=True)
        assert result == {}

    def test_open_tags(self):
        from dtflow.utils.text_parser import parse_generic_tags

        result = parse_generic_tags("<a>hello<b>world", strict=False)
        assert "a" in result
        assert "b" in result

    def test_mixed(self):
        from dtflow.utils.text_parser import parse_generic_tags

        result = parse_generic_tags("<a>closed</a><b>open")
        assert result["a"] == "closed"
        assert result["b"] == "open"

    def test_empty(self):
        from dtflow.utils.text_parser import parse_generic_tags

        assert parse_generic_tags("") == {}
        assert parse_generic_tags(None) == {}


# ============ MetricsCalculator 测试 ============


class TestMetricsCalculator:
    def test_basic_metrics(self):
        import pandas as pd

        from dtflow.eval import MetricsCalculator

        df = pd.DataFrame({"pred": ["A", "B", "A", "B", "A"], "label": ["A", "B", "B", "B", "A"]})
        calc = MetricsCalculator(df, pred_col="pred", label_col="label")
        metrics = calc.get_metrics()

        assert 0 <= metrics["accuracy"] <= 1
        assert 0 <= metrics["precision"] <= 1
        assert 0 <= metrics["recall"] <= 1
        assert metrics["confusion_matrix"] is not None
        assert metrics["classification_report"] is not None

    def test_perfect_accuracy(self):
        import pandas as pd

        from dtflow.eval import MetricsCalculator

        df = pd.DataFrame({"pred": ["A", "B", "C"], "label": ["A", "B", "C"]})
        calc = MetricsCalculator(df, pred_col="pred", label_col="label")
        assert calc.get_metrics()["accuracy"] == 1.0

    def test_classification_report_markdown(self):
        import pandas as pd

        from dtflow.eval import MetricsCalculator

        df = pd.DataFrame({"pred": ["A", "B"], "label": ["A", "B"]})
        calc = MetricsCalculator(df, pred_col="pred", label_col="label")
        md = calc.format_classification_report_as_markdown()
        assert "| Label |" in md
        assert "Precision" in md

    def test_confusion_matrix_markdown(self):
        import pandas as pd

        from dtflow.eval import MetricsCalculator

        df = pd.DataFrame({"pred": ["A", "B"], "label": ["A", "B"]})
        calc = MetricsCalculator(df, pred_col="pred", label_col="label")
        md = calc.format_confusion_matrix_as_markdown()
        assert "真实值/预测值" in md


# ============ export_eval_report 测试 ============


class TestExportEvalReport:
    def test_basic_export(self):
        import pandas as pd

        from dtflow.eval import export_eval_report

        df = pd.DataFrame({"pred": ["A", "B", "A", "B"], "label": ["A", "B", "B", "B"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = export_eval_report(
                df, pred_col="pred", label_col="label", record_folder=tmpdir, input_name="test"
            )
            assert (result_path / "metrics.md").exists()
            assert (result_path / "result.jsonl").exists()
            assert (result_path / "bad_case.jsonl").exists()

    def test_incremental_dirs(self):
        import pandas as pd

        from dtflow.eval import export_eval_report

        df = pd.DataFrame({"pred": ["A", "B"], "label": ["A", "B"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = export_eval_report(
                df, pred_col="pred", label_col="label", record_folder=tmpdir, input_name="x"
            )
            p2 = export_eval_report(
                df, pred_col="pred", label_col="label", record_folder=tmpdir, input_name="x"
            )
            # 第二次应该序号+1
            assert p1.name.startswith("1-")
            assert p2.name.startswith("2-")


# ============ CLI eval 内部函数测试 ============


class TestEvalInternals:
    def test_stage1_clean_think_tags(self):
        from dtflow.cli.eval import _stage1_clean

        assert _stage1_clean("<think>分析中</think>正面") == "正面"

    def test_stage1_clean_code_block(self):
        from dtflow.cli.eval import _stage1_clean

        assert _stage1_clean('```json\n"答案"\n```') == '"答案"'

    def test_stage1_clean_plain(self):
        from dtflow.cli.eval import _stage1_clean

        assert _stage1_clean("普通文本") == "普通文本"

    def test_stage1_clean_none(self):
        from dtflow.cli.eval import _stage1_clean

        assert _stage1_clean(None) == ""

    def test_parse_pipeline(self):
        from dtflow.cli.eval import _parse_pipeline

        assert _parse_pipeline("direct") == ["direct"]
        assert _parse_pipeline("tag:标签 | index:0") == ["tag:标签", "index:0"]
        assert _parse_pipeline("lines | index:1") == ["lines", "index:1"]

    def test_apply_op_direct(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op("hello", "direct") == "hello"

    def test_apply_op_tag(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op("<标签>内容</标签>", "tag:标签") == "内容"

    def test_apply_op_json_key(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op('{"result": "yes"}', "json_key:result") == "yes"

    def test_apply_op_index(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op("a,b,c", "index:1") == "b"
        assert _apply_op("a|b|c", "index:2", sep="|") == "c"

    def test_apply_op_line(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op("line1\nline2\nline3", "line:0") == "line1"
        assert _apply_op("line1\nline2\nline3", "line:-1") == "line3"

    def test_apply_op_regex(self):
        from dtflow.cli.eval import _apply_op

        assert _apply_op("score=85", r"regex:score=(\d+)") == "85"

    def test_run_pipeline_simple(self):
        from dtflow.cli.eval import _run_pipeline

        assert _run_pipeline("hello", ["direct"]) == "hello"

    def test_run_pipeline_chain(self):
        from dtflow.cli.eval import _run_pipeline

        text = '{"result": "a,b,c"}'
        result = _run_pipeline(text, ["json_key:result", "index:1"])
        assert result == "b"

    def test_run_pipeline_lines(self):
        from dtflow.cli.eval import _run_pipeline

        text = "a|1\nb|2\nc|3"
        result = _run_pipeline(text, ["lines", "index:1"], sep="|")
        assert result == ["1", "2", "3"]

    def test_parse_mapping(self):
        from dtflow.cli.eval import _parse_mapping

        assert _parse_mapping("是:1,否:0") == {"是": "1", "否": "0"}
        assert _parse_mapping("a:x, b:y") == {"a": "x", "b": "y"}

    def test_auto_detect_label_col(self):
        import pandas as pd

        from dtflow.cli.eval import _auto_detect_label_col

        df = pd.DataFrame({"content": ["a"], "label": ["b"]})
        assert _auto_detect_label_col(df) == "label"

    def test_auto_detect_label_col_nested(self):
        import pandas as pd

        from dtflow.cli.eval import _auto_detect_label_col

        df = pd.DataFrame({"content": ["a"], "meta": [{"label": "b"}]})
        assert _auto_detect_label_col(df) == "meta.label"

    def test_auto_detect_label_col_none(self):
        import pandas as pd

        from dtflow.cli.eval import _auto_detect_label_col

        df = pd.DataFrame({"content": ["a"], "score": [1]})
        assert _auto_detect_label_col(df) is None


# ============ CLI 端到端测试 ============


class TestEvalCLI:
    def _write_jsonl(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def test_basic_eval(self):
        from dtflow.cli.eval import eval

        with tempfile.TemporaryDirectory() as tmpdir:
            result_file = os.path.join(tmpdir, "result.jsonl")
            self._write_jsonl(
                result_file,
                [
                    {"content": "正面", "label": "正面"},
                    {"content": "负面", "label": "负面"},
                    {"content": "正面", "label": "负面"},
                ],
            )
            output_dir = os.path.join(tmpdir, "record")
            eval(result_file, label_col="label", output_dir=output_dir)

            # 验证输出目录存在
            record_dirs = [
                p for p in os.listdir(os.path.join(output_dir, "result")) if not p.startswith(".")
            ]
            assert len(record_dirs) == 1
            record_path = os.path.join(output_dir, "result", record_dirs[0])
            assert os.path.exists(os.path.join(record_path, "metrics.md"))
            assert os.path.exists(os.path.join(record_path, "result.jsonl"))
            assert os.path.exists(os.path.join(record_path, "bad_case.jsonl"))

    def test_eval_with_source(self):
        from dtflow.cli.eval import eval

        with tempfile.TemporaryDirectory() as tmpdir:
            result_file = os.path.join(tmpdir, "result.jsonl")
            source_file = os.path.join(tmpdir, "source.jsonl")
            self._write_jsonl(
                result_file,
                [
                    {"content": "正面"},
                    {"content": "负面"},
                ],
            )
            self._write_jsonl(
                source_file,
                [
                    {"label": "正面"},
                    {"label": "负面"},
                ],
            )
            output_dir = os.path.join(tmpdir, "record")
            eval(result_file, source=source_file, label_col="label", output_dir=output_dir)

            record_dirs = [
                p for p in os.listdir(os.path.join(output_dir, "result")) if not p.startswith(".")
            ]
            assert len(record_dirs) == 1

    def test_eval_with_extract_and_mapping(self):
        from dtflow.cli.eval import eval

        with tempfile.TemporaryDirectory() as tmpdir:
            result_file = os.path.join(tmpdir, "result.jsonl")
            self._write_jsonl(
                result_file,
                [
                    {"content": "<标签>是</标签>", "label": "1"},
                    {"content": "<标签>否</标签>", "label": "0"},
                ],
            )
            output_dir = os.path.join(tmpdir, "record")
            eval(
                result_file,
                label_col="label",
                extract="tag:标签",
                mapping="是:1,否:0",
                output_dir=output_dir,
            )

            record_dirs = [
                p for p in os.listdir(os.path.join(output_dir, "result")) if not p.startswith(".")
            ]
            assert len(record_dirs) == 1

    def test_eval_with_nested_label(self):
        from dtflow.cli.eval import eval

        with tempfile.TemporaryDirectory() as tmpdir:
            result_file = os.path.join(tmpdir, "result.jsonl")
            self._write_jsonl(
                result_file,
                [
                    {"content": "A", "meta": {"label": "A"}},
                    {"content": "B", "meta": {"label": "B"}},
                ],
            )
            output_dir = os.path.join(tmpdir, "record")
            eval(result_file, label_col="meta.label", output_dir=output_dir)

            record_dirs = [
                p for p in os.listdir(os.path.join(output_dir, "result")) if not p.startswith(".")
            ]
            assert len(record_dirs) == 1

    def test_eval_with_think_tags(self):
        from dtflow.cli.eval import eval

        with tempfile.TemporaryDirectory() as tmpdir:
            result_file = os.path.join(tmpdir, "result.jsonl")
            self._write_jsonl(
                result_file,
                [
                    {"content": "<think>分析中</think>正面", "label": "正面"},
                    {"content": "<think>嗯</think>负面", "label": "负面"},
                ],
            )
            output_dir = os.path.join(tmpdir, "record")
            eval(result_file, label_col="label", output_dir=output_dir)

            record_path = os.path.join(output_dir, "result")
            record_dirs = [d for d in os.listdir(record_path) if not d.startswith(".")]
            metrics_path = os.path.join(record_path, record_dirs[0], "metrics.md")
            with open(metrics_path) as f:
                content = f.read()
            # accuracy 应该是 1.0
            assert "1.0000" in content
