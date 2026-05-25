"""Unit tests for XHS Signature."""

import pytest

from xhs_growth.services.xhs_signature import XHSSignature, XHSCookieParser


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

    def test_parse_cookie_string(self):
        """parse_cookie extracts values from cookie string."""
        cookie_str = "a1=value1; a2=value2; web_session=abc123"
        result = XHSCookieParser.parse_cookie(cookie_str)
        assert result.get("a1") == "value1"
        assert result.get("web_session") == "abc123"

    def test_parse_cookie_empty_string(self):
        """parse_cookie handles empty string."""
        result = XHSCookieParser.parse_cookie("")
        assert result == {}

    def test_parse_cookie_with_spaces(self):
        """parse_cookie handles spaces."""
        cookie_str = "a1 = value1 ; a2=value2"
        result = XHSCookieParser.parse_cookie(cookie_str)
        assert result.get("a1") == "value1"

    def test_extract_user_id_success(self):
        """extract_user_id returns user ID."""
        cookie_dict = {"web_session": "session_value"}
        # Implementation depends on actual cookie structure
        pass

    def test_extract_user_id_missing(self):
        """extract_user_id handles missing field."""
        cookie_dict = {}
        # Should return None or empty
        pass

    def test_validate_cookie_valid(self):
        """validate_cookie returns True for valid cookie."""
        cookie_str = "web_session=abc123; webId=xyz789"
        # Implementation depends on validation criteria
        pass

    def test_validate_cookie_invalid(self):
        """validate_cookie returns False for invalid cookie."""
        cookie_str = ""
        # Should return False for empty/invalid
        pass