
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ghost_agent.core.agent import GhostAgent, GhostContext

@pytest.fixture
def mock_context():
    context = MagicMock(spec=GhostContext)
    context.args = MagicMock()
    context.args.temperature = 0.5
    context.args.max_context = 8000
    context.args.smart_memory = 0.0
    context.args.use_planning = False
    context.sandbox_dir = "/tmp/sandbox"
    context.memory_system = None
    context.profile_memory = None
    context.skill_memory = None
    # Mock scratchpad to avoid AttributeError
    context.scratchpad = MagicMock()
    context.scratchpad.list_all.return_value = "Mock Scratchpad Content"
    # Mock LLM client
    context.llm_client = MagicMock()
    context.llm_client.chat_completion = AsyncMock()
    return context

@pytest.mark.asyncio
async def test_handle_chat_json_parsing_failure(mock_context):
    """Test that invalid JSON arguments in tool calls are handled gracefully and reported."""
    agent = GhostAgent(mock_context)
    
    # Mock LLM response with broken JSON in tool arguments
    mock_message = {
        "role": "assistant",
        "content": "Using tool...",
        "tool_calls": [{
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": '{"filename": "test.txt", "content": "missing_brace"' # Broken JSON
            }
        }]
    }
    
    mock_context.llm_client.chat_completion.return_value = {
        "choices": [{"message": mock_message}]
    }
    
    # We need to simulate the loop or inspection.
    # Since handle_chat is a complex loop, we'll check the messages list after execution.
    # To break the loop, we can make the second call return finish_reason="stop" or just no tool calls.
    # Actually, if we use side_effect on chat_completion, we can control subsequent turns.
    
    # Turn 1: Returns broken tool call -> Agent should catch error and append tool error message.
    # Turn 2: Returns final answer "Fixed".
    
    mock_context.llm_client.chat_completion.side_effect = [
        {"choices": [{"message": mock_message}]}, # Turn 1
        {"choices": [{"message": {"role": "assistant", "content": "Fixed", "tool_calls": []}}]} # Turn 2
    ]
    
    # We need to pass a list that we can inspect
    messages = [{"role": "user", "content": "Write a file"}]
    background_tasks = MagicMock()
    
    final_content, _, _ = await agent.handle_chat({"messages": messages, "model": "test-model"}, background_tasks)
    
    # Inspect the messages passed to the LLM in the SECOND call (Turn 2)
    # The agent might create a new messages list internally (e.g. pruning), so checking the original 'messages' list is unreliable.
    assert mock_context.llm_client.chat_completion.call_count >= 2
    
    # Get the arguments of the second call
    second_call_args = mock_context.llm_client.chat_completion.call_args_list[1]
    # call_args_list entries are (args, kwargs). chat_completion is called with a single payload dict.
    payload = second_call_args[0][0] 
    sent_messages = payload["messages"]
    
    # We expect a tool message with the error
    error_tool_msg = next((m for m in sent_messages if m.get("role") == "tool" and "Error: Invalid JSON arguments" in str(m.get("content"))), None)
    
    assert error_tool_msg is not None, "Agent did not report Invalid JSON arguments back to the context in the next turn."
    assert error_tool_msg["tool_call_id"] == "call_123"
    assert "write_file" in error_tool_msg["name"]
    assert "Invalid JSON arguments" in error_tool_msg["content"]
