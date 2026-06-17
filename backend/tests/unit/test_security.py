from core.security import api_keys_match


def test_api_keys_match_exact_value():
    assert api_keys_match("swarm-factory-dev-key", "swarm-factory-dev-key")


def test_api_keys_match_quoted_compose_value():
    assert api_keys_match('"swarm-factory-dev-key"', "swarm-factory-dev-key")
    assert api_keys_match("'swarm-factory-dev-key'", "swarm-factory-dev-key")


def test_api_keys_match_padded_compose_value():
    assert api_keys_match("swarm-factory-dev-key ", "swarm-factory-dev-key")
    assert api_keys_match(' "swarm-factory-dev-key" ', "swarm-factory-dev-key")


def test_api_keys_match_rejects_different_values():
    assert not api_keys_match('"wrong-key"', "swarm-factory-dev-key")
