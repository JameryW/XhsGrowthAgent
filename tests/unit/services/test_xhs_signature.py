"""Unit tests for XHS cookie parser (fake signature removed)."""

import pytest

from backend.services.xhs_client import XHSSignatureUnavailableError, _HTTPClient
from backend.services.xhs_signature import XHSCookieParser


class TestXHSCookieParser:
    """Tests for XHS cookie parsing."""

    def test_extract_from_string(self):
        cookie_str = "a1=value1; a2=value2; web_session=abc123"
        result = XHSCookieParser.extract_from_string(cookie_str)
        assert result.get("a1") == "value1"
        assert result.get("web_session") == "abc123"

    def test_extract_from_string_empty(self):
        result = XHSCookieParser.extract_from_string("")
        assert result == {}

    def test_extract_from_string_with_spaces(self):
        cookie_str = "a1 = value1 ; a2=value2"
        result = XHSCookieParser.extract_from_string(cookie_str)
        assert result.get("a1") == "value1"

    def test_is_valid_true(self):
        cookie_str = "a1=valid_long_value_12345; web_session=abc"
        assert XHSCookieParser.is_valid(cookie_str) is True

    def test_is_valid_false_short_a1(self):
        cookie_str = "a1=short; web_session=abc"
        assert XHSCookieParser.is_valid(cookie_str) is False

    def test_is_valid_false_no_a1(self):
        cookie_str = "web_session=abc"
        assert XHSCookieParser.is_valid(cookie_str) is False


class TestSignatureUnavailable:
    """HTTP paths that needed fake sign must fail closed."""

    @pytest.mark.asyncio
    async def test_http_request_raises_signature_unavailable(self):
        client = _HTTPClient(cookie="a1=valid_long_value_12345")
        with pytest.raises(XHSSignatureUnavailableError) as exc:
            await client._request("/api/sns/web/v1/homefeed", {"cursor": ""})
        assert exc.value.error_code == "signature_unavailable"
        await client.close()

    @pytest.mark.asyncio
    async def test_monitor_keywords_does_not_swallow_signature_unavailable(self):
        from backend.services.xhs_client import XHSClient

        client = XHSClient(cookie="a1=valid_long_value_12345", use_browser=False)
        with pytest.raises(XHSSignatureUnavailableError) as exc:
            await client.monitor_keywords(["穿搭"])
        assert exc.value.error_code == "signature_unavailable"
        await client.close()

    def test_xhs_signature_class_removed(self):
        import backend.services.xhs_signature as mod

        assert not hasattr(mod, "XHSSignature")
