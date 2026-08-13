def balance(entries):
    return sum(entry["amount_cents"] for entry in entries)
