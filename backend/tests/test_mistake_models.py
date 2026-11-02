from app.models.enums import CAUSE_TYPES, MISTAKE_STATUSES, CauseType, MistakeStatus


def test_mistake_status_values_match_schema():
    assert MISTAKE_STATUSES == ("待订正", "已订正", "已掌握")
    assert MistakeStatus.MASTERED.value == "已掌握"


def test_cause_types_include_unknown_for_missing_answer():
    assert set(CAUSE_TYPES) == {
        "概念不清", "计算失误", "审题偏差", "方法不当", "知识遗忘", "时间不足", "unknown",
    }
    assert CauseType.UNKNOWN.value == "unknown"


def test_mistake_table_columns_and_constraints():
    from app.models.mistake import Mistake

    assert Mistake.__tablename__ == "mistakes"
    names = {c.name for c in Mistake.__table__.constraints}
    assert "uq_mistakes_user_question" in names
    assert "ck_mistakes_status" in names
    assert "ck_mistakes_correct_streak" in names
    # 默认值走 server_default（与 questions 表一致），不是 Python 端 default
    assert "待订正" in str(Mistake.__table__.c.status.server_default.arg)
    assert str(Mistake.__table__.c.correct_streak.server_default.arg) == "0"


def test_mistake_analysis_unique_and_cascade():
    from app.models.mistake_analysis import MistakeAnalysis

    assert MistakeAnalysis.__tablename__ == "mistake_analyses"
    fk = next(iter(MistakeAnalysis.__table__.foreign_keys))
    assert fk.ondelete == "CASCADE"
    names = {c.name for c in MistakeAnalysis.__table__.constraints}
    assert "uq_mistake_analyses_mistake_id" in names