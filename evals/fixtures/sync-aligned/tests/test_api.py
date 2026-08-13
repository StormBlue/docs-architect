from src.api import health


def test_health_version():
    assert set(health()) == {"status", "version"}
