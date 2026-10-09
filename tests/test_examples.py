"""Generated examples must survive the documented conversion/validation loop."""

import random
import runpy
from pathlib import Path

from dtflow.presets import get_preset
from dtflow.schema import openai_chat_schema, sharegpt_schema


def test_sharegpt_examples_and_explicit_invalid_fixture():
    generator = runpy.run_path(str(Path(__file__).parents[1] / "examples/make_examples.py"))
    rows = generator["make_sharegpt"](random.Random(generator["SEED"]))
    convert = get_preset("openai_chat")
    assert len(rows) == 100
    for row in rows:
        assert sharegpt_schema().validate(row).valid, row["id"]
        assert openai_chat_schema().validate(convert(row)).valid, row["id"]

    invalid = generator["make_invalid_sharegpt"]()[0]
    assert not sharegpt_schema().validate(invalid).valid
    assert not openai_chat_schema().validate(convert(invalid)).valid
