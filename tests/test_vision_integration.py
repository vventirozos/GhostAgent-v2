import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from src.ghost_agent.tools.registry import get_active_tool_definitions, get_available_tools
from src.ghost_agent.core.llm import LLMClient
from src.ghost_agent.tools.vision import tool_vision_analysis
from src.ghost_agent.core.agent import GhostAgent, GhostContext

class DummyArgs:
    model = "default-model"
    temperature = 0.5
    max_context = 8192
    smart_memory = 0.0
    use_planning = False
    anonymous = False

@pytest.fixture
def mock_llm_client():
    client = MagicMock(spec=LLMClient)
    client.vision_clients = []
    return client

@pytest.fixture
def mock_context(mock_llm_client, tmp_path):
    ctx = MagicMock(spec=GhostContext)
    ctx.args = DummyArgs()
    ctx.llm_client = mock_llm_client
    ctx.sandbox_dir = tmp_path
    ctx.tor_proxy = None
    ctx.scratchpad = MagicMock()
    return ctx

def test_get_active_tool_definitions_no_vision(mock_context):
    mock_context.llm_client.vision_clients = None
    tools = get_active_tool_definitions(mock_context)
    names = [t["function"]["name"] for t in tools]
    assert "vision_analysis" not in names

def test_get_active_tool_definitions_with_vision(mock_context):
    mock_context.llm_client.vision_clients = [{"client": AsyncMock()}]
    tools = get_active_tool_definitions(mock_context)
    names = [t["function"]["name"] for t in tools]
    assert "vision_analysis" in names

def test_get_available_tools_vision_injected(mock_context):
    mock_context.llm_client.vision_clients = [{"client": AsyncMock()}]
    tools = get_available_tools(mock_context)
    assert "vision_analysis" in tools
    assert callable(tools["vision_analysis"])

@pytest.mark.asyncio
async def test_tool_vision_analysis_no_configured_nodes(mock_context):
    mock_context.llm_client.vision_clients = None
    res = await tool_vision_analysis(
        action="describe_picture",
        target="file.jpg",
        llm_client=mock_context.llm_client,
        sandbox_dir=mock_context.sandbox_dir
    )
    assert "Systems ERROR" in res or "offline" in res.lower() or "SYSTEM ERROR" in res

@pytest.mark.asyncio
async def test_llm_client_vision_routing():
    # Test llm_client get_vision_node logic
    client = LLMClient(upstream_url="http://fake", visual_nodes=[{"url": "http://vision", "model": "vision-model"}])
    assert client.vision_clients is not None
    assert len(client.vision_clients) == 1
    
    node = client.get_vision_node()
    assert node["model"] == "vision-model"

    # Mock post response
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "vision response"}}]}
    mock_resp.raise_for_status = MagicMock()
    client.vision_clients[0]["client"].post = AsyncMock(return_value=mock_resp)
    
    # Test chat_completion with use_vision=True
    res = await client.chat_completion({"model": "test"}, use_vision=True)
    assert res["choices"][0]["message"]["content"] == "vision response"

    await client.close()
