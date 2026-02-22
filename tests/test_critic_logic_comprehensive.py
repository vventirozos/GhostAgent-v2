
import pytest
import json
import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock, patch
from ghost_agent.core.agent import GhostAgent, GhostContext

def create_mock_context():
    ctx = MagicMock(spec=GhostContext)
    ctx.args = MagicMock()
    ctx.args.temperature = 0.5
    ctx.args.max_context = 8000
    ctx.args.smart_memory = 0.0
    # Disable planning to prevent planner from consuming a mock response
    ctx.args.use_planning = False
    
    ctx.llm_client = MagicMock()
    ctx.llm_client.chat_completion = AsyncMock()
    ctx.memory_system = MagicMock()
    ctx.profile_memory = MagicMock()
    ctx.profile_memory.get_context_string = MagicMock(return_value="")
    ctx.scratchpad = MagicMock()
    ctx.scratchpad.list_all = MagicMock(return_value="None.")
    ctx.skill_memory = MagicMock()
    ctx.cached_sandbox_state = None
    ctx.scheduler = None
    ctx.sandbox_dir = "/tmp/sandbox"
    return ctx

@pytest.mark.asyncio
async def test_critic_runs_on_success(capsys):
    """Test that critic runs when execution_failure_count is 0."""
    long_code = "print('line')\n" * 11
    
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "execute",
            "arguments": json.dumps({"content": long_code})
        }
    }
    
    ctx = create_mock_context()
    ctx.llm_client.chat_completion.side_effect = [
        {"choices": [{"message": {"content": None, "tool_calls": [tool_call]}}]}, # Turn 1
        {"choices": [{"message": {"content": "Done"}}]} # Turn 2
    ]
    
    async def mock_execute(**kwargs):
        return "EXIT CODE: 0"
    
    async def critic_side_effect(*args, **kwargs):
        print("CRITIC_CALLED_TOKEN", file=sys.stderr)
        return (True, None, "Approved")

    with patch('ghost_agent.core.agent.GhostAgent._run_critic_check', new_callable=AsyncMock) as mock_critic:
        mock_critic.side_effect = critic_side_effect
        
        agent = GhostAgent(context=ctx)
        agent.available_tools = {"execute": mock_execute}
        
        await agent.handle_chat({"messages": [{"role": "user", "content": "Run code"}]}, MagicMock())
        
        captured = capsys.readouterr()
        assert "CRITIC_CALLED_TOKEN" in captured.err, "Critic should have been called"

@pytest.mark.asyncio
async def test_critic_skips_on_failure(capsys):
    """Test that critic skips when execution_failure_count > 0."""
    code_1 = "import sys\nprint('fail')"
    tool_call_1 = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "execute",
            "arguments": json.dumps({"content": code_1})
        }
    }
    
    long_code = "print('line')\n" * 11
    tool_call_2 = {
        "id": "call_2",
        "type": "function",
        "function": {
            "name": "execute",
            "arguments": json.dumps({"content": long_code})
        }
    }
    
    ctx = create_mock_context()
    ctx.llm_client.chat_completion.side_effect = [
        {"choices": [{"message": {"content": "Try 1", "tool_calls": [tool_call_1]}}]}, 
        {"choices": [{"message": {"content": "Try 2", "tool_calls": [tool_call_2]}}]},
        {"choices": [{"message": {"content": "Done"}}]} 
    ]
    
    async def mock_execute(content=None, **kwargs):
        # Initial turn fails
        if content and "fail" in content:
            return "EXIT CODE: 1\nSTDOUT/STDERR: Error"
        return "EXIT CODE: 0"
    
    async def critic_side_effect(*args, **kwargs):
        print("CRITIC_CALLED_TOKEN", file=sys.stderr)
        return (True, None, "Approved")
        
    with patch('ghost_agent.core.agent.GhostAgent._run_critic_check', new_callable=AsyncMock) as mock_critic:
        mock_critic.side_effect = critic_side_effect
        
        agent = GhostAgent(context=ctx)
        agent.available_tools = {"execute": mock_execute}
        
        await agent.handle_chat({"messages": [{"role": "user", "content": "Fix bug"}]}, MagicMock())
        
        captured = capsys.readouterr()
        assert "CRITIC_CALLED_TOKEN" not in captured.err, "Critic should NOT have been called"
