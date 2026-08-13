from src.payments.service import capture


def test_capture():
    assert capture("p-1")["status"] == "captured"
