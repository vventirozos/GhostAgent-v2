
import pytest
from unittest.mock import MagicMock
from ghost_agent.core.agent import GhostAgent, GhostContext

@pytest.fixture
def mock_agent():
    ctx = MagicMock(spec=GhostContext)
    agent = GhostAgent(context=ctx)
    return agent

def test_process_rolling_window_does_not_mutate_original_message(mock_agent):
    # Setup test data
    long_content = "A" * 25000
    original_tool_msg = {"role": "tool", "name": "exec", "content": long_content}
    
    # Needs to be far back in history to trigger compression (> 5 messages from end)
    messages = [original_tool_msg] + [{"role": "user", "content": str(i)} for i in range(15)]
    
    # Process rolling window
    # We expect compression to happen on the first message
    processed_messages = mock_agent.process_rolling_window(messages, max_tokens=10000)
    
    # Check if processed message IS compressed
    compressed_msg = processed_messages[0]
    assert len(str(compressed_msg["content"])) < 25000
    assert "... [OLD DATA COMPRESSED] ..." in str(compressed_msg["content"])
    
    # Check if ORIGINAL message is UNCHANGED
    assert original_tool_msg["content"] == ("A" * 25000)
    assert len(original_tool_msg["content"]) == 25000
    assert "... [OLD DATA COMPRESSED] ..." not in original_tool_msg["content"]
