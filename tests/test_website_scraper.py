"""Unit tests for WebsiteScraperClient (offline; requests.get is mocked).

First transport-level mock in this test suite: every other agents/clients/*
wrapper is only exercised indirectly (mocked at the client-object boundary by
the tests of the agent that consumes it), since resend_client.py /
tavily_client.py have no dedicated test files of their own.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.clients.website_scraper import WebsiteScraperClient, is_social_url


def _mock_response(text, status_ok=True):
    response = MagicMock()
    response.text = text
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = Exception("HTTP error")
    return response


# --- is_social_url --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com/cafex",
        "https://m.facebook.com/cafex",
        "https://instagram.com/cafex",
        "https://www.instagram.com/cafex",
        "https://wa.me/59899123456",
        "https://api.whatsapp.com/send?phone=59899123456",
        "https://beacons.ai/cafex",
        "https://linktr.ee/cafex",
    ],
)
def test_is_social_url_true_for_known_platforms(url):
    assert is_social_url(url) is True


def test_is_social_url_false_for_a_real_business_site():
    assert is_social_url("https://cafex.com") is False


# --- find_email: skips without a network call ------------------------------------


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_skips_social_url_without_network_call(mock_get):
    client = WebsiteScraperClient()
    assert client.find_email("https://www.instagram.com/cafex") is None
    mock_get.assert_not_called()


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_returns_none_for_empty_url(mock_get):
    client = WebsiteScraperClient()
    assert client.find_email("") is None
    assert client.find_email(None) is None
    mock_get.assert_not_called()


# --- find_email: mailto / regex extraction ---------------------------------------


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_prefers_mailto_link(mock_get):
    mock_get.return_value = _mock_response(
        '<a href="mailto:hola@cafex.com">Escribinos</a> visible@other.com'
    )
    assert WebsiteScraperClient().find_email("https://cafex.com") == "hola@cafex.com"


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_strips_mailto_query_string(mock_get):
    mock_get.return_value = _mock_response(
        '<a href="mailto:hola@cafex.com?subject=Hola">Escribinos</a>'
    )
    assert WebsiteScraperClient().find_email("https://cafex.com") == "hola@cafex.com"


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_falls_back_to_generic_regex(mock_get):
    mock_get.return_value = _mock_response("Escribinos a hola@cafex.com para consultas.")
    assert WebsiteScraperClient().find_email("https://cafex.com") == "hola@cafex.com"


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_returns_none_when_nothing_found(mock_get):
    mock_get.return_value = _mock_response("<html><body>Bienvenidos a Cafe X</body></html>")
    assert WebsiteScraperClient().find_email("https://cafex.com") is None


# --- find_email: never raises -----------------------------------------------------


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_returns_none_on_timeout(mock_get):
    mock_get.side_effect = TimeoutError("timed out")
    assert WebsiteScraperClient().find_email("https://cafex.com") is None


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_returns_none_on_connection_error(mock_get):
    mock_get.side_effect = ConnectionError("dns failure")
    assert WebsiteScraperClient().find_email("https://cafex.com") is None


@patch("agents.clients.website_scraper.requests.get")
def test_find_email_returns_none_on_http_error_status(mock_get):
    mock_get.return_value = _mock_response("<html></html>", status_ok=False)
    assert WebsiteScraperClient().find_email("https://cafex.com") is None
