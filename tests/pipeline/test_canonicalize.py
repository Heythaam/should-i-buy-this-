import pytest

from app.pipeline.canonicalize import CanonicalProductId, InvalidProductURLError, canonicalize


def test_standard_product_url_resolves_to_canonical_id():
    result = canonicalize("https://amazon.com/dp/B08N5WRWNW")

    assert result == CanonicalProductId("amazon:B08N5WRWNW")


def test_gp_product_url_shape_is_also_supported():
    result = canonicalize("https://www.amazon.com/gp/product/B08N5WRWNW")

    assert result == CanonicalProductId("amazon:B08N5WRWNW")


def test_gp_aw_d_mobile_url_shape_is_supported():
    result = canonicalize("https://www.amazon.com/gp/aw/d/B08N5WRWNW")

    assert result == CanonicalProductId("amazon:B08N5WRWNW")


def test_exec_obidos_asin_legacy_url_shape_is_supported():
    result = canonicalize("https://www.amazon.com/exec/obidos/ASIN/B08N5WRWNW")

    assert result == CanonicalProductId("amazon:B08N5WRWNW")


def test_trailing_dot_hostname_is_accepted_as_the_same_domain():
    result = canonicalize("https://www.amazon.com./dp/B08N5WRWNW")

    assert result == CanonicalProductId("amazon:B08N5WRWNW")


def test_same_asin_different_tracking_params_yield_identical_id():
    first = canonicalize("https://www.amazon.com/dp/B08N5WRWNW?ref=sr_1_1&tag=abc-20")
    second = canonicalize("https://www.amazon.com/dp/B08N5WRWNW/ref=cm_sw_r_cp_apa?th=1")

    assert first == second


def test_color_variant_url_resolves_to_that_variants_own_id():
    base = canonicalize("https://www.amazon.com/dp/B08N5WRWNW")
    variant = canonicalize("https://www.amazon.com/dp/B08N5KWB9H")

    assert base != variant
    assert variant == CanonicalProductId("amazon:B08N5KWB9H")


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://www.ebay.com/itm/123456",
        "not a url at all",
        "https://www.amazon.com/s?k=echo+dot",  # no ASIN
        "",
        "https://notamazon.com/dp/B08N5WRWNW",
        "https://amazon.evil.com/dp/B08N5WRWNW",
        "ftp://amazon.com/dp/B08N5WRWNW",  # non-HTTP(S) scheme
        "https://www.amazon.com/dp/B08N5WRWNWEXTRA",  # ASIN segment too long
    ],
)
def test_non_amazon_or_malformed_url_raises(bad_url):
    with pytest.raises(InvalidProductURLError):
        canonicalize(bad_url)


def test_canonical_id_is_a_plain_string_with_expected_format():
    result = canonicalize("https://www.amazon.com/dp/b08n5wrwnw")  # lowercase ASIN in URL

    assert str(result) == "amazon:B08N5WRWNW"
