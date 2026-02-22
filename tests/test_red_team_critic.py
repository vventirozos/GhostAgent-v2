import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock
from ghost_agent.core.agent import GhostAgent

@pytest.fixture
def agent():
    context = MagicMock()
    context.llm_client.chat_completion = AsyncMock()
    agent = GhostAgent(context)
    return agent

@pytest.mark.asyncio
async def test_critic_safe_pass(agent):
    """Test that the critic approves safe code."""
    agent.context.llm_client.chat_completion.return_value = {
        "choices": [{"message": {"content": '{"status": "APPROVED"}'}}]
    }
    
    approved, revised, critique = await agent._run_critic_check("print('Hello')", "Say hello", "test-model")
    
    assert approved is True
    assert revised is None
    assert critique == "Approved"

@pytest.mark.asyncio
async def test_critic_antigravity_trap(agent):
    """Test that the critic intervenes on unsafe code (import antigravity)."""
    agent.context.llm_client.chat_completion.return_value = {
        "choices": [{"message": {"content": '{"status": "REVISED", "critique": "import antigravity opens a GUI browser and will hang the headless sandbox.", "revised_code": "print(\'XKCD Antigravity bypassed\')"}'}}]
    }
    
    code = "import antigravity"
    approved, revised, critique = await agent._run_critic_check(code, "Run python easter egg", "test-model")
    
    assert approved is False
    assert revised == "print('XKCD Antigravity bypassed')"
    assert "antigravity" in critique

@pytest.mark.asyncio
async def test_critic_fail_open(agent):
    """Test that network failures result in a Fail-Open state (True)."""
    agent.context.llm_client.chat_completion.side_effect = httpx.ConnectTimeout("Timeout")
    
    approved, revised, critique = await agent._run_critic_check("print('risk?')", "Unknown task", "test-model")
    
    assert approved is True
    assert revised is None
    assert "Fail-Open" in critique
