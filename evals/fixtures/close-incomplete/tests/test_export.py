from src.export import export


def test_all_records():
    assert export([1, 2]) == "1\n2"
