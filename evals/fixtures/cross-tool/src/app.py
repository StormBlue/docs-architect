from .ledger import balance


def account_balance(entries):
    return {"balance_cents": balance(entries)}
