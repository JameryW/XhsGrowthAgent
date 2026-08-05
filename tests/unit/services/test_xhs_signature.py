"""Unit tests for XHS Signature."""

from backend.services.xhs_signature import XHSCookieParser, XHSSignature


class TestXHSSignature:
    """Tests for XHS signature generation."""

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
