from src.logging import log_record


def test_field_order():
    assert list(log_record("info", "ready")) == ["message", "level"]
