from app.core.api_keys import generate_api_key, hash_api_key


def test_generated_api_keys_are_unique() -> None:
    first_key = generate_api_key()
    second_key = generate_api_key()

    assert first_key.startswith("frk_")
    assert second_key.startswith("frk_")
    assert first_key != second_key


def test_hash_is_deterministic() -> None:
    api_key = generate_api_key()

    assert hash_api_key(api_key) == hash_api_key(api_key)


def test_hash_does_not_equal_raw_key() -> None:
    api_key = generate_api_key()
    digest = hash_api_key(api_key)

    assert digest != api_key
    assert len(digest) == 64


def test_different_keys_have_different_hashes() -> None:
    first_key = generate_api_key()
    second_key = generate_api_key()

    assert hash_api_key(first_key) != hash_api_key(second_key)
