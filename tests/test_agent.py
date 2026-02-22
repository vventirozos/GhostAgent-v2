
import pytest
from unittest.mock import MagicMock
from ghost_agent.core.agent import GhostAgent, GhostContext

@pytest.fixture
def mock_agent():
    ctx = MagicMock(spec=GhostContext)
    ctx.llm_client = MagicMock()
    ctx.llm_client.vision_clients = None
    # Mocking attributes accessed in specific methods if needed
    agent = GhostAgent(context=ctx)
    return agent

def test_prepare_planning_context_truncation(mock_agent):
    # Case 1: Short output
    tools_run = [{"content": "Short output"}]
    result = mock_agent._prepare_planning_context(tools_run)
    assert result == "Tool [unknown]: Short output"

    # Case 2: Long output (Over 5000 chars)
    # create a string of 6000 chars
    long_content = "A" * 30000
    tools_run = [{"content": long_content}]
    result = mock_agent._prepare_planning_context(tools_run)
    
    # Expect truncation
    expected_marker = "\n\n... [TRUNCATED: Tool output too long. Showing top results only.]"
    
    # Result = "Tool [unknown]: " + 4800-chars + marker
    # The length depends on the "Tool [unknown]: " prefix length which is 16 chars
    # So 16 + 4800 + len(marker) = 4816 + 65 = 4881 approximately
    
    assert len(result) < 10000
    assert expected_marker in result
    assert "A" * 4000 in result
    assert result.endswith(expected_marker)

def test_process_rolling_window_deduplication(mock_agent):
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "tool", "name": "exec", "content": "Result A"},
        {"role": "tool", "name": "exec", "content": "Result A"}, # Duplicate
        {"role": "assistant", "content": "Memory updated..."},  # Meta-chatter
        {"role": "assistant", "content": "Real response"}
    ]
    
    # Note: The method iterates BACKWARDS and keeps the NEWEST unique tool output.
    # And it filters specific assistant phrases.
    
    clean = mock_agent.process_rolling_window(messages, max_tokens=1000)
    
    # Check deduplication
    tool_msgs = [m for m in clean if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "Result A"
    
    # Check meta-chatter filtering
    assist_msgs = [m for m in clean if m["role"] == "assistant"]
    assert len(assist_msgs) == 1
    assert assist_msgs[0]["content"] == "Real response"

def test_agent_semaphore_initialization(mock_agent):
    """
    Verify that the agent's semaphore is initialized to 10 to allow
    concurrent background tasks and user chats.
    """
    # In asyncio.Semaphore, the initial value is stored in _value (internal) 
    # but we can also just check if we can acquire it multiple times in a loop 
    # or check the internal attribute for a unit test.
    # checking internal _value is implementation specific but simplest for unit test.
    assert mock_agent.agent_semaphore._value == 10

