"""Unit tests for XHS Signature."""


from backend.services.xhs_signature import XHSCookieParser, XHSSignature


class TestXHSSignature:
    """Tests for XHS signature generation."""

    def test_generate_sign_returns_string(self):
        """generate_sign returns a string."""
        params = {"keyword": "test", "page": 1}
        result = XHSSignature.generate_sign(params)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_sign_with_timestamp(self):
        """generate_sign accepts custom timestamp."""
        params = {"keyword": "test"}
        timestamp = 1700000000000
        result = XHSSignature.generate_sign(params, timestamp=timestamp)
        assert isinstance(result, str)
        # Shield format: version:timestamp:signature
        assert "1700000000000" in result

    def test_generate_sign_format(self):
        """generate_sign returns correct shield format."""
        params = {"keyword": "test"}
        result = XHSSignature.generate_sign(params)
        # Format: version:timestamp:signature_base64
        parts = result.split(":")
        assert len(parts) == 3
        assert parts[0] == XHSSignature.SHIELD_VERSION

    def test_generate_sign_consistent_for_same_params(self):
        """Same params + same timestamp = same signature."""
        params = {"keyword": "test", "page": 1}
        timestamp = 1700000000000
        result1 = XHSSignature.generate_sign(params, timestamp=timestamp)
        result2 = XHSSignature.generate_sign(params, timestamp=timestamp)
        assert result1 == result2

    def test_generate_sign_different_for_different_params(self):
        """Different params = different signature."""
        timestamp = 1700000000000
        params1 = {"keyword": "test"}
        params2 = {"keyword": "other"}
        result1 = XHSSignature.generate_sign(params1, timestamp=timestamp)
        result2 = XHSSignature.generate_sign(params2, timestamp=timestamp)
        assert result1 != result2

    def test_generate_sign_handles_none_values(self):
        """generate_sign handles None values in params."""
        params = {"keyword": "test", "optional": None}
        result = XHSSignature.generate_sign(params)
        assert isinstance(result, str)

    def test_generate_sign_empty_params(self):
        """generate_sign handles empty params."""
        params = {}
        result = XHSSignature.generate_sign(params)
        assert isinstance(result, str)

    def test_generate_x_s_returns_string(self):
        """generate_x_s returns a string."""
        params = {"keyword": "test"}
        result = XHSSignature.generate_x_s(params)
        assert isinstance(result, str)

    def test_generate_x_s_with_timestamp(self):
        """generate_x_s accepts custom timestamp."""
        params = {"keyword": "test"}
        timestamp = 1700000000000
        result = XHSSignature.generate_x_s(params, timestamp=timestamp)
        assert isinstance(result, str)

    def test_sign_key_defined(self):
        """SIGN_KEY is defined."""
        assert XHSSignature.SIGN_KEY is not None
        assert len(XHSSignature.SIGN_KEY) > 0

    def test_shield_version_defined(self):
        """SHIELD_VERSION is defined."""
        assert XHSSignature.SHIELD_VERSION == "1"


class TestXHSCookieParser:
    """Tests for XHS cookie parsing."""

    def test_extract_from_string(self):
        """extract_from_string extracts values from cookie string."""
        cookie_str = "a1=value1; a2=value2; web_session=abc123"
        result = XHSCookieParser.extract_from_string(cookie_str)
        assert result.get("a1") == "value1"
        assert result.get("web_session") == "abc123"

    def test_extract_from_string_empty(self):
        """extract_from_string handles empty string."""
        result = XHSCookieParser.extract_from_string("")
        assert result == {}

    def test_extract_from_string_with_spaces(self):
        """extract_from_string handles spaces."""
        cookie_str = "a1 = value1 ; a2=value2"
        result = XHSCookieParser.extract_from_string(cookie_str)
        assert result.get("a1") == "value1"

    def test_get_user_id_success(self):
        """get_user_id returns user ID."""
        cookie_str = "a1=user123456; web_session=abc123"
        result = XHSCookieParser.get_user_id(cookie_str)
        assert result == "user123456"

    def test_get_user_id_from_customer_sso_sid(self):
        """get_user_id extracts from customer-sso-sid."""
        cookie_str = "customer-sso-sid=sid123; a1=short"
        result = XHSCookieParser.get_user_id(cookie_str)
        assert result == "sid123"

    def test_get_user_id_missing(self):
        """get_user_id handles missing field."""
        cookie_str = "other=value"
        result = XHSCookieParser.get_user_id(cookie_str)
        assert result is None

    def test_is_valid_true(self):
        """is_valid returns True for valid cookie."""
        cookie_str = "a1=valid_long_value_12345; web_session=abc"
        result = XHSCookieParser.is_valid(cookie_str)
        assert result is True

    def test_is_valid_false_short_a1(self):
        """is_valid returns False for short a1."""
        cookie_str = "a1=short; web_session=abc"
        result = XHSCookieParser.is_valid(cookie_str)
        assert result is False

    def test_is_valid_false_no_a1(self):
        """is_valid returns False for missing a1."""
        cookie_str = "web_session=abc"
        result = XHSCookieParser.is_valid(cookie_str)
        assert result is False