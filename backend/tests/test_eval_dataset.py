"""S1-7 数据集与配置校验；不连 DB、不调网络。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import (  # noqa: E402
    DatasetError,
    EvalConfigError,
    QACase,
    load_config,
    load_dataset,
    validate_gold_chunks,
)


def _case(index: int, *, refuse: bool = False) -> dict:
    return {
        "id": f"q{index:03d}",
        "question": f"问题 {index}",
        "scope": "函数",
        "gold_chunk_ids": [] if refuse else [index],
        "should_refuse": refuse,
    }


def _write_cases(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "qa_set.jsonl"
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in cases) + "\n",
        encoding="utf-8",
    )
    return path


def _valid_cases() -> list[dict]:
    return [_case(i) for i in range(1, 21)] + [
        _case(i, refuse=True) for i in range(21, 31)
    ]


def test_load_dataset_accepts_30_cases(tmp_path) -> None:
    cases = load_dataset(_write_cases(tmp_path, _valid_cases()))
    assert len(cases) == 30
    assert cases[0].id == "q001"
    assert cases[-1].should_refuse is True


def test_load_dataset_rejects_too_few(tmp_path) -> None:
    with pytest.raises(DatasetError, match="20"):
        load_dataset(_write_cases(tmp_path, _valid_cases()[:19]))


def test_load_dataset_rejects_too_many(tmp_path) -> None:
    cases = _valid_cases() + [_case(31)]
    with pytest.raises(DatasetError, match="30"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_duplicate_id(tmp_path) -> None:
    cases = _valid_cases()
    cases[1]["id"] = cases[0]["id"]
    with pytest.raises(DatasetError, match="重复"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_missing_field(tmp_path) -> None:
    cases = _valid_cases()
    del cases[0]["scope"]
    with pytest.raises(DatasetError, match="scope"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_bad_json_line(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(_case(1), ensure_ascii=False) + "\nnot-json\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match="2"):
        load_dataset(path)


def test_load_dataset_rejects_answerable_without_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[0]["gold_chunk_ids"] = []
    with pytest.raises(DatasetError, match="gold"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_refusal_with_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[20]["gold_chunk_ids"] = [1]
    with pytest.raises(DatasetError, match="gold"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_duplicate_or_nonpositive_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[0]["gold_chunk_ids"] = [1, 1]
    with pytest.raises(DatasetError, match="重复"):
        load_dataset(_write_cases(tmp_path, cases))
    cases[0]["gold_chunk_ids"] = [0]
    with pytest.raises(DatasetError, match="正整数"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(path)


def test_load_config_accepts_three_configs() -> None:
    for name in ("vector", "hybrid", "hybrid_rerank"):
        cfg = load_config(ROOT / "eval" / "configs" / f"{name}.json")
        assert cfg.name == name
        assert cfg.top_n == 5


def test_load_config_rejects_top_n_not_5(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {"name": "vector", "retrieval": "vector", "top_k": 20, "top_n": 4}
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError, match="top_n"):
        load_config(path)


def test_load_config_rejects_invalid_retrieval(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {"name": "x", "retrieval": "magic", "top_k": 20, "top_n": 5}
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError):
        load_config(path)


def test_load_config_rejects_rerank_top_k_below_top_n(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "name": "hybrid_rerank",
                "retrieval": "hybrid_rerank",
                "top_k": 20,
                "top_n": 5,
                "rerank_candidates": 30,
                "rerank_top_k": 4,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError, match="rerank_top_k"):
        load_config(path)


def test_validate_gold_chunks_rejects_missing() -> None:
    cases = [QACase(**_case(1))]
    with pytest.raises(DatasetError, match="不存在"):
        validate_gold_chunks(cases, {2: 102})


def test_validate_gold_chunks_accepts_present() -> None:
    cases = [QACase(**_case(1))]
    validate_gold_chunks(cases, {1: 102})