import hmac


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def api_keys_match(provided: str, expected: str) -> bool:
    """Compare API keys while tolerating Compose interpolation padding/quotes."""
    return hmac.compare_digest(_strip_outer_quotes(provided), _strip_outer_quotes(expected))
