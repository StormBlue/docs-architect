from src.pagination import page


def test_page_respects_limit():
    assert page([1, 2, 3], 0, 2) == [1, 2]
