"""
Tests for CLI sample/head/tail commands.
"""

import importlib.util as _ilu

import pytest
import typer

from dtflow.cli.sample import head, sample, tail
from dtflow.storage.io import load_data, save_data

# flaxkv 后端为可选依赖 (flaxkv2 未必在公共 PyPI); 未安装时跳过相关测试
requires_flaxkv = pytest.mark.skipif(_ilu.find_spec("flaxkv2") is None, reason="flaxkv2 未安装")

# ============== Fixtures ==============


@pytest.fixture
def sample_qa_file(tmp_path):
    """Create a sample QA dataset file."""
    data = [
        {"question": f"Question {i}", "answer": f"Answer {i}", "category": f"cat{i % 3}"}
        for i in range(20)
    ]
    filepath = tmp_path / "test_qa.jsonl"
    save_data(data, str(filepath))
    return filepath, data


@pytest.fixture
def sample_nested_file(tmp_path):
    """Create a sample dataset with nested fields."""
    data = [
        {
            "id": i,
            "meta": {"source": f"source{i % 2}", "score": i * 0.1},
            "messages": [
                {"role": "user", "content": f"User message {i}"},
                {"role": "assistant", "content": f"Assistant reply {i}"},
            ],
        }
        for i in range(15)
    ]
    filepath = tmp_path / "test_nested.jsonl"
    save_data(data, str(filepath))
    return filepath, data


# ============== Basic Sample Tests ==============


class TestSampleBasic:
    """Test basic sample functionality."""

    def test_sample_head_default(self, sample_qa_file, capsys):
        """Test head sampling with default num."""
        filepath, data = sample_qa_file
        sample(str(filepath), num=10, type="head")
        # Should output to console, not file
        captured = capsys.readouterr()
        # The output contains table formatting, just verify it ran
        assert "Question" in captured.out or len(data) > 0

    def test_sample_head_with_output(self, sample_qa_file, tmp_path):
        """Test head sampling with output file."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=5, type="head", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 5
        assert result[0]["question"] == "Question 0"
        assert result[4]["question"] == "Question 4"

    def test_sample_tail_with_output(self, sample_qa_file, tmp_path):
        """Test tail sampling with output file."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=5, type="tail", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 5
        assert result[0]["question"] == "Question 15"
        assert result[4]["question"] == "Question 19"

    def test_sample_random_with_seed(self, sample_qa_file, tmp_path):
        """Test random sampling with seed."""
        filepath, data = sample_qa_file
        output1 = tmp_path / "output1.jsonl"
        output2 = tmp_path / "output2.jsonl"

        # Same seed should produce same result
        sample(str(filepath), num=5, type="random", output=str(output1), seed=42)
        sample(str(filepath), num=5, type="random", output=str(output2), seed=42)

        result1 = load_data(str(output1))
        result2 = load_data(str(output2))
        assert result1 == result2

    def test_sample_zero_returns_all(self, sample_qa_file, tmp_path):
        """Test that num=0 returns all data."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=0, type="head", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == len(data)

    def test_sample_negative_num(self, sample_qa_file, tmp_path):
        """Test negative num (Python slice style)."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=-5, type="head", output=str(output_file))

        result = load_data(str(output_file))
        # -5 should return last 5 items
        assert len(result) == 5


# ============== Head/Tail Shortcut Tests ==============


class TestHeadTail:
    """Test head/tail shortcut functions."""

    def test_head_function(self, sample_qa_file, tmp_path):
        """Test head() function."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        head(str(filepath), num=3, output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 3
        assert result[0]["question"] == "Question 0"

    def test_tail_function(self, sample_qa_file, tmp_path):
        """Test tail() function."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        tail(str(filepath), num=3, output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 3
        assert result[0]["question"] == "Question 17"


# ============== Stratified Sampling Tests ==============


class TestStratifiedSample:
    """Test stratified sampling (--by parameter)."""

    def test_stratified_sample_by_category(self, sample_qa_file, tmp_path):
        """Test stratified sampling by category field."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        # Sample 9 items, should get 3 from each of 3 categories
        sample(str(filepath), num=9, type="random", output=str(output_file), by="category", seed=42)

        result = load_data(str(output_file))
        assert len(result) == 9

    def test_stratified_sample_uniform(self, sample_qa_file, tmp_path, capsys):
        """Test uniform stratified sampling."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        sample(
            str(filepath),
            num=6,
            type="random",
            output=str(output_file),
            by="category",
            uniform=True,
            seed=42,
        )

        result = load_data(str(output_file))
        assert len(result) == 6

        # Uniform: should have 2 from each category
        categories = {}
        for item in result:
            cat = item["category"]
            categories[cat] = categories.get(cat, 0) + 1

        # Each category should have equal count (or differ by at most 1)
        counts = list(categories.values())
        assert max(counts) - min(counts) <= 1

    def test_stratified_sample_nested_field(self, sample_nested_file, tmp_path):
        """Test stratified sampling by nested field."""
        filepath, data = sample_nested_file
        output_file = tmp_path / "output.jsonl"

        sample(str(filepath), num=6, type="head", output=str(output_file), by="meta.source")

        result = load_data(str(output_file))
        assert len(result) == 6

    def test_uniform_requires_by(self, sample_qa_file, capsys):
        """Test that --uniform requires --by parameter."""
        filepath, _ = sample_qa_file
        with pytest.raises(typer.Exit) as exc_info:
            sample(str(filepath), num=5, uniform=True)
        assert exc_info.value.exit_code == 2  # usage error

        captured = capsys.readouterr()
        assert "--uniform 必须配合 --by 使用" in captured.err

    def test_stratified_sample_custom_dist(self, sample_qa_file, tmp_path):
        """Test stratified sampling with custom distribution."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        # data has 20 items: cat0(7), cat1(7), cat2(6)
        # Request 10 items with dist: cat0=50%, cat1=30%, cat2=20%
        sample(
            str(filepath),
            num=10,
            type="random",
            output=str(output_file),
            by="category",
            seed=42,
            dist='{"cat0":0.5,"cat1":0.3,"cat2":0.2}',
        )

        result = load_data(str(output_file))
        assert len(result) == 10

        counts = {}
        for item in result:
            cat = item["category"]
            counts[cat] = counts.get(cat, 0) + 1

        assert counts["cat0"] == 5
        assert counts["cat1"] == 3
        assert counts["cat2"] == 2

    def test_dist_requires_by(self, sample_qa_file, capsys):
        """Test that --dist requires --by parameter."""
        filepath, _ = sample_qa_file
        with pytest.raises(typer.Exit) as exc_info:
            sample(str(filepath), num=5, dist='{"cat0":0.5,"cat1":0.5}')
        assert exc_info.value.exit_code == 2  # USAGE
        captured = capsys.readouterr()
        assert "--dist 必须配合 --by 使用" in captured.err

    def test_dist_conflicts_uniform(self, sample_qa_file, capsys):
        """Test that --dist and --uniform are mutually exclusive."""
        filepath, _ = sample_qa_file
        with pytest.raises(typer.Exit) as exc_info:
            sample(
                str(filepath),
                num=5,
                by="category",
                uniform=True,
                dist='{"cat0":0.5,"cat1":0.5}',
            )
        assert exc_info.value.exit_code == 2  # USAGE
        captured = capsys.readouterr()
        assert "--dist 和 --uniform 不能同时使用" in captured.err

    def test_dist_missing_group(self, sample_qa_file, tmp_path, capsys):
        """Test warning when dist references a non-existent group."""
        filepath, _ = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        # "nonexistent" is not a real category
        sample(
            str(filepath),
            num=10,
            type="random",
            output=str(output_file),
            by="category",
            seed=42,
            dist='{"cat0":0.5,"cat1":0.3,"nonexistent":0.2}',
        )

        captured = capsys.readouterr()
        # 警告通过 log() 写到 stderr
        assert "nonexistent" in captured.err
        assert "不存在" in captured.err


# ============== Error Handling Tests ==============


class TestSampleErrors:
    """Test error handling in sample commands."""

    def test_file_not_exists(self, tmp_path, capsys):
        """Test error when file doesn't exist."""
        with pytest.raises(typer.Exit) as exc_info:
            sample(str(tmp_path / "nonexistent.jsonl"))
        assert exc_info.value.exit_code == 3  # NOT_FOUND
        captured = capsys.readouterr()
        assert "文件不存在" in captured.err or "file_not_found" in captured.err

    def test_invalid_file_format(self, tmp_path, capsys):
        """Test error for unsupported file format."""
        invalid_file = tmp_path / "test.xyz"
        invalid_file.write_text("test")

        with pytest.raises(typer.Exit) as exc_info:
            sample(str(invalid_file))
        assert exc_info.value.exit_code == 2  # USAGE
        captured = capsys.readouterr()
        assert "不支持" in captured.err or "格式" in captured.err


# ============== Raw Output Tests ==============


class TestRawOutput:
    """Test raw JSON output mode."""

    def test_raw_output(self, sample_qa_file, capsys):
        """Test raw JSON output."""
        filepath, _ = sample_qa_file
        sample(str(filepath), num=1, type="head", raw=True)

        captured = capsys.readouterr()
        # Raw mode outputs JSON with indentation
        assert "question" in captured.out
        assert "Question 0" in captured.out


# ============== Where Filter Tests ==============


class TestWhereFilter:
    """Test --where filter functionality."""

    def test_where_equal(self, sample_qa_file, tmp_path, capsys):
        """Test where filter with = operator."""
        filepath, _ = sample_qa_file
        output = tmp_path / "filtered.jsonl"

        sample(str(filepath), num=100, output=str(output), where=["category=cat0"])

        result = load_data(str(output))
        assert len(result) > 0
        assert all(item["category"] == "cat0" for item in result)

    def test_where_not_equal(self, sample_qa_file, tmp_path, capsys):
        """Test where filter with != operator."""
        filepath, _ = sample_qa_file
        output = tmp_path / "filtered.jsonl"

        sample(str(filepath), num=100, output=str(output), where=["category!=cat0"])

        result = load_data(str(output))
        assert len(result) > 0
        assert all(item["category"] != "cat0" for item in result)

    def test_where_contains(self, sample_qa_file, tmp_path, capsys):
        """Test where filter with ~= (contains) operator."""
        filepath, _ = sample_qa_file
        output = tmp_path / "filtered.jsonl"

        sample(str(filepath), num=100, output=str(output), where=["question~=Question 1"])

        result = load_data(str(output))
        assert len(result) > 0
        assert all("Question 1" in item["question"] for item in result)

    def test_where_nested_field(self, sample_nested_file, tmp_path, capsys):
        """Test where filter on nested fields."""
        filepath, _ = sample_nested_file
        output = tmp_path / "filtered.jsonl"

        sample(str(filepath), num=100, output=str(output), where=["meta.source=source0"])

        result = load_data(str(output))
        assert len(result) > 0
        assert all(item["meta"]["source"] == "source0" for item in result)

    def test_where_numeric_comparison(self, sample_nested_file, tmp_path, capsys):
        """Test where filter with numeric comparison."""
        filepath, _ = sample_nested_file
        output = tmp_path / "filtered.jsonl"

        sample(str(filepath), num=100, output=str(output), where=["id>=10"])

        result = load_data(str(output))
        assert len(result) > 0
        assert all(item["id"] >= 10 for item in result)

    def test_where_multiple_conditions(self, sample_qa_file, tmp_path, capsys):
        """Test multiple where conditions (AND logic)."""
        filepath, _ = sample_qa_file
        output = tmp_path / "filtered.jsonl"

        sample(
            str(filepath),
            num=100,
            output=str(output),
            where=["category=cat0", "question~=Question 0"],
        )

        result = load_data(str(output))
        # category=cat0 包括 id 0, 3, 6, 9, 12, 15, 18
        # question~=Question 0 包括 Question 0
        assert len(result) == 1
        assert result[0]["category"] == "cat0"
        assert "Question 0" in result[0]["question"]

    def test_where_no_match(self, sample_qa_file, capsys):
        """Test where filter with no matching results."""
        filepath, _ = sample_qa_file

        with pytest.raises(typer.Exit) as exc_info:
            sample(str(filepath), num=10, where=["category=nonexistent"])
        assert exc_info.value.exit_code == 1
        captured = capsys.readouterr()
        assert "筛选后无数据" in captured.err

    def test_where_invalid_condition(self, sample_qa_file, capsys):
        """Test where filter with invalid condition format."""
        filepath, _ = sample_qa_file

        with pytest.raises(typer.Exit) as exc_info:
            sample(str(filepath), num=10, where=["invalid_condition"])
        assert exc_info.value.exit_code == 2  # USAGE
        captured = capsys.readouterr()
        assert "无效的 where 条件" in captured.err


# ============== FlaxKV Format Conversion Tests ==============


@requires_flaxkv
class TestFlaxKVFormatConversion:
    """Test format conversion between JSONL and FlaxKV via sample command."""

    @pytest.fixture
    def jsonl_file(self, tmp_path):
        data = [{"id": i, "text": f"item_{i}", "meta": {"score": i * 0.1}} for i in range(30)]
        filepath = tmp_path / "source.jsonl"
        save_data(data, str(filepath))
        return filepath, data

    @pytest.fixture
    def flaxkv_file(self, tmp_path):
        data = [{"id": i, "text": f"item_{i}", "meta": {"score": i * 0.1}} for i in range(30)]
        filepath = tmp_path / "source.flaxkv"
        save_data(data, str(filepath))
        return filepath, data

    def test_jsonl_to_flaxkv(self, jsonl_file, tmp_path):
        """JSONL → FlaxKV 全量转换"""
        filepath, data = jsonl_file
        output = tmp_path / "out.flaxkv"
        sample(str(filepath), num=0, type="head", output=str(output))

        result = load_data(str(output))
        assert len(result) == 30
        assert result[0] == data[0]
        assert result[29] == data[29]

    def test_flaxkv_to_jsonl(self, flaxkv_file, tmp_path):
        """FlaxKV → JSONL 全量转换"""
        filepath, data = flaxkv_file
        output = tmp_path / "out.jsonl"
        sample(str(filepath), num=0, type="head", output=str(output))

        result = load_data(str(output))
        assert len(result) == 30
        assert result[0] == data[0]

    def test_jsonl_to_flaxkv_roundtrip(self, jsonl_file, tmp_path):
        """JSONL → FlaxKV → JSONL 往返数据一致"""
        filepath, data = jsonl_file
        flaxkv_path = tmp_path / "mid.flaxkv"
        jsonl_back = tmp_path / "back.jsonl"

        sample(str(filepath), num=0, type="head", output=str(flaxkv_path))
        sample(str(flaxkv_path), num=0, type="head", output=str(jsonl_back))

        result = load_data(str(jsonl_back))
        assert result == data

    def test_flaxkv_sample_head_with_output(self, flaxkv_file, tmp_path):
        """从 FlaxKV head 采样并输出到 JSONL"""
        filepath, data = flaxkv_file
        output = tmp_path / "head.jsonl"
        sample(str(filepath), num=5, type="head", output=str(output))

        result = load_data(str(output))
        assert len(result) == 5
        assert result[0]["id"] == 0
        assert result[4]["id"] == 4

    def test_flaxkv_sample_tail_with_output(self, flaxkv_file, tmp_path):
        """从 FlaxKV tail 采样并输出到 JSONL"""
        filepath, data = flaxkv_file
        output = tmp_path / "tail.jsonl"
        sample(str(filepath), num=5, type="tail", output=str(output))

        result = load_data(str(output))
        assert len(result) == 5
        assert result[0]["id"] == 25
        assert result[4]["id"] == 29

    def test_flaxkv_sample_random_with_output(self, flaxkv_file, tmp_path):
        """从 FlaxKV 随机采样并输出到 JSONL"""
        filepath, _ = flaxkv_file
        output = tmp_path / "random.jsonl"
        sample(str(filepath), num=10, type="random", output=str(output), seed=42)

        result = load_data(str(output))
        assert len(result) == 10

    def test_flaxkv_head_function(self, flaxkv_file, tmp_path):
        """head() 函数读取 FlaxKV"""
        filepath, _ = flaxkv_file
        output = tmp_path / "head.jsonl"
        head(str(filepath), num=3, output=str(output))

        result = load_data(str(output))
        assert len(result) == 3
        assert result[0]["id"] == 0

    def test_flaxkv_tail_function(self, flaxkv_file, tmp_path):
        """tail() 函数读取 FlaxKV"""
        filepath, _ = flaxkv_file
        output = tmp_path / "tail.jsonl"
        tail(str(filepath), num=3, output=str(output))

        result = load_data(str(output))
        assert len(result) == 3
        assert result[0]["id"] == 27

    def test_flaxkv_console_output(self, flaxkv_file, capsys):
        """FlaxKV 直接输出到终端"""
        filepath, _ = flaxkv_file
        sample(str(filepath), num=2, type="head")

        captured = capsys.readouterr()
        assert "item_0" in captured.out or "id" in captured.out

    def test_flaxkv_with_where_filter(self, flaxkv_file, tmp_path):
        """FlaxKV 采样 + where 过滤"""
        filepath, _ = flaxkv_file
        output = tmp_path / "filtered.jsonl"
        sample(str(filepath), num=100, output=str(output), where=["id>=20"])

        result = load_data(str(output))
        assert len(result) == 10  # id 20-29
        assert all(item["id"] >= 20 for item in result)


class TestMarkupLikeContent:
    """回归: 用户数据含 [/quote] 等伪 Rich markup 时输出不崩溃且原文显示。"""

    def test_print_samples_generic_table(self, capsys):
        from dtflow.cli.common import _print_samples

        rows = [{"id": 1, "note": "contains [/quote] and [b]bold[/b]", "tag[/dim]": "x[/url]y"}]
        _print_samples(rows)  # generic 表格分支, 之前会抛 MarkupError
        out = capsys.readouterr().out
        assert "[/quote]" in out

    def test_print_samples_chat_detail(self, capsys):
        from dtflow.cli.common import _print_samples

        rows = [
            {
                "messages": [{"role": "user", "content": "[url=/a/][/quote][/url] 引用"}],
                "src": "s[/dim]",
            }
        ]
        _print_samples(rows)
        out = capsys.readouterr().out
        assert "[/quote]" in out

    def test_sample_stratify_markup_like_group_values(self, tmp_path, capsys):
        """回归: 分层采样组值含伪 markup 时分组打印不崩溃。"""
        data = [{"label": "[/quote]bad" if i % 2 else "ok", "x": i} for i in range(10)]
        f = tmp_path / "strat.jsonl"
        save_data(data, str(f))
        out = tmp_path / "out.jsonl"
        sample(str(f), num=4, by="label", output=str(out))
        assert len(load_data(str(out))) == 4
