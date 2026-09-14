"""WBI signing — the part of the Bilibili adapter that silently breaks everything
if it is even slightly wrong, and that cannot be verified against the live API
from a test suite."""

import pytest

from chekhovsgun.adapters.wbi import (
    MIXIN_KEY_ENC_TAB,
    WbiSigner,
    keys_from_nav,
    mixin_key,
    sign_params,
)

# The documented reference pair.
IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
EXPECTED_MIXIN = "ea1db124af3c7062474693fa704f4ff8"


def test_permutation_table_is_a_complete_64_entry_permutation():
    assert len(MIXIN_KEY_ENC_TAB) == 64
    assert sorted(MIXIN_KEY_ENC_TAB) == list(range(64))


def test_mixin_key_matches_the_reference_vector():
    assert mixin_key(IMG_KEY, SUB_KEY) == EXPECTED_MIXIN


def test_mixin_key_is_always_32_chars():
    assert len(mixin_key("a" * 32, "b" * 32)) == 32


def test_sign_params_is_deterministic_for_a_fixed_timestamp():
    params = {"foo": "114", "bar": "514", "baz": 1919810}
    first = sign_params(params, EXPECTED_MIXIN, timestamp=1702204169)
    second = sign_params(params, EXPECTED_MIXIN, timestamp=1702204169)
    assert first["w_rid"] == second["w_rid"]
    assert first["wts"] == 1702204169
    assert len(first["w_rid"]) == 32


def test_sign_params_is_order_independent():
    a = sign_params({"foo": "1", "bar": "2"}, EXPECTED_MIXIN, timestamp=1)
    b = sign_params({"bar": "2", "foo": "1"}, EXPECTED_MIXIN, timestamp=1)
    assert a["w_rid"] == b["w_rid"]


def test_sign_params_strips_the_forbidden_characters():
    """Bilibili strips !'()* before signing; signing them produces a bad w_rid."""
    with_specials = sign_params({"k": "a!b'c(d)e*f"}, EXPECTED_MIXIN, timestamp=1)
    without = sign_params({"k": "abcdef"}, EXPECTED_MIXIN, timestamp=1)
    assert with_specials["w_rid"] == without["w_rid"]


def test_sign_params_does_not_mutate_its_input():
    params = {"foo": "1"}
    sign_params(params, EXPECTED_MIXIN, timestamp=1)
    assert params == {"foo": "1"}


def test_keys_from_nav_extracts_filenames():
    payload = {
        "data": {
            "wbi_img": {
                "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
            }
        }
    }
    assert keys_from_nav(payload) == (IMG_KEY, SUB_KEY)


def test_keys_from_nav_rejects_a_missing_payload():
    with pytest.raises(ValueError):
        keys_from_nav({"data": {}})


def test_signer_caches_the_key_and_refetches_when_forced():
    calls = {"n": 0}

    def nav() -> dict:
        calls["n"] += 1
        return {
            "data": {
                "wbi_img": {
                    "img_url": f"https://x/{IMG_KEY}.png",
                    "sub_url": f"https://x/{SUB_KEY}.png",
                }
            }
        }

    signer = WbiSigner(nav)
    assert signer.key() == EXPECTED_MIXIN
    signer.key()
    signer.sign({"a": 1})
    assert calls["n"] == 1
    signer.key(force=True)
    assert calls["n"] == 2
