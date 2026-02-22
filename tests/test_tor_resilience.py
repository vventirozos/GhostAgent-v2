import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from src.ghost_agent.utils.helpers import request_new_tor_identity, helper_fetch_url_content
from src.ghost_agent.tools.search import tool_search_ddgs, tool_deep_research

def test_request_new_tor_identity_success():
    with patch("socket.socket") as mock_socket:
        mock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_instance
        # Simulate successful auth and newnym
        mock_instance.recv.side_effect = [b"250 OK\r\n", b"250 OK\r\n"]
        
        success, msg = request_new_tor_identity(password="testpass")
        
        assert success is True
        assert "renewed successfully" in msg
        mock_instance.sendall.assert_any_call(b'AUTHENTICATE "testpass"\r\n')
        mock_instance.sendall.assert_any_call(b'SIGNAL NEWNYM\r\n')

def test_request_new_tor_identity_auth_fail():
    with patch("socket.socket") as mock_socket:
        mock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_instance
        mock_instance.recv.return_value = b"515 Authentication failed\r\n"
        
        success, msg = request_new_tor_identity()
        
        assert success is False
        assert "Tor Auth failed" in msg

@pytest.mark.asyncio
async def test_helper_fetch_url_content_retry_403():
    mock_curl = MagicMock()
    mock_requests = MagicMock()
    mock_curl.requests = mock_requests
    
    with patch.dict("sys.modules", {"curl_cffi": mock_curl, "curl_cffi.requests": mock_requests}), \
         patch("src.ghost_agent.utils.helpers.request_new_tor_identity") as mock_renew, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("os.getenv") as mock_getenv:
        
        mock_getenv.return_value = "socks5://127.0.0.1:9050"
        
        mock_session_instance = AsyncMock()
        mock_requests.AsyncSession.return_value.__aenter__.return_value = mock_session_instance
        
        # Responses: first 403, then 200
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "Forbidden"
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "<html><body>Some content</body></html>"
        
        mock_session_instance.get.side_effect = [resp_403, resp_200]
        
        result = await helper_fetch_url_content("http://example.com")
        
        assert "Some content" in result
        assert mock_renew.call_count == 1
        assert mock_session_instance.get.call_count == 2
        mock_sleep.assert_called_with(5)

@pytest.mark.asyncio
async def test_tool_search_ddgs_retry():
    mock_ddgs_module = MagicMock()
    mock_ddgs_class = MagicMock()
    mock_ddgs_module.DDGS = mock_ddgs_class

    with patch.dict("sys.modules", {"ddgs": mock_ddgs_module}), \
         patch("importlib.util.find_spec", return_value=True), \
         patch("src.ghost_agent.utils.helpers.request_new_tor_identity") as mock_renew, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
         
        # Make DDGS context manager raise exception first time, return results second time
        mock_ddgs_instance = MagicMock()
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance
        
        mock_ddgs_instance.text.side_effect = [Exception("Tor blocked"), [{"title": "t", "body": "b", "href": "h"}]]
        
        result = await tool_search_ddgs("test query", "socks5://127.0.0.1:9050")
        
        assert "1. t" in result
        # Check that it called renew because it had tor_proxy
        assert mock_renew.call_count == 1
        mock_sleep.assert_called_with(5)

@pytest.mark.asyncio
async def test_tool_deep_research_retry():
    mock_ddgs_module = MagicMock()
    mock_ddgs_class = MagicMock()
    mock_ddgs_module.DDGS = mock_ddgs_class

    with patch.dict("sys.modules", {"ddgs": mock_ddgs_module}), \
         patch("importlib.util.find_spec", return_value=True), \
         patch("src.ghost_agent.utils.helpers.request_new_tor_identity") as mock_renew, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
         
        mock_ddgs_instance = MagicMock()
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance
        
        # Exception first, then valid results
        mock_ddgs_instance.text.side_effect = [Exception("Tor blocked deep"), [{"title": "t1", "body": "b1", "href": "http://example.com/good"}]]
        
        # mock semaphore and requests for deep research parsing
        with patch("src.ghost_agent.tools.search.helper_fetch_url_content", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = "Mocked content of site"
            result = await tool_deep_research("test query deep", anonymous=True, tor_proxy="socks5://127.0.0.1:9050")
            
            assert "Mocked content of site" in result
            assert "http://example.com/good" in result
            assert mock_renew.call_count == 1
            mock_sleep.assert_called_with(5)
