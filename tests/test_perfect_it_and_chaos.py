import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ghost_agent.core.agent import GhostAgent

@pytest.fixture
def agent():
    context = MagicMock()
    context.llm_client.chat_completion = AsyncMock()
    # Ensure args are set defaults
    context.args.use_planning = False
    context.args.smart_memory = 0.0
    context.args.temperature = 0.1
    context.args.max_context = 8000
    context.args.perfect_it = True
    context.sandbox_dir = "/tmp"
    context.memory_system = MagicMock()
    context.profile_memory = MagicMock()
    context.profile_memory.get_context_string.return_value = ""
    
    agent = GhostAgent(context)
    # Mock available tools
    agent.available_tools = {
        "execute": AsyncMock(return_value="Exit Code: 0"),
        "test_tool": AsyncMock(return_value="Result")
    }
    return agent

@pytest.mark.asyncio
async def test_perfect_it_security_strip(agent):
    """
    Verify that when 'Perfect It' protocol is triggered, 
    the 'tools' and 'tool_choice' are removed from the LLM payload.
    """
    # 1. Setup: Agent mocks
    # We need a flow: 
    # Turn 1: AI calls 'execute' (heavy tool)
    # Turn 2: AI returns final content. 
    # Logic then triggers "Perfect It".
    
    agent.context.llm_client.chat_completion.side_effect = [
        # Call 1: Agent decides to use execute
        {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "call_1",
            "function": {"name": "execute", "arguments": '{"code": "print(1)"}'}
        }]}}]},
        # Call 2: Perfect It (triggered automatically)
        {"choices": [{"message": {"content": "Optimization suggestion"}}]}
    ]
    
    agent.available_tools["execute"].return_value = "EXIT CODE: 0"
    
    await agent.handle_chat({"messages": [{"role": "user", "content": "Run code"}]}, [])
    
    # Verify calls
    # Call 1: Agent generates tool call
    # Tool executes (no LLM call)
    # Loop breaks because tool executed
    # Perfect It triggers (Call 2)
    calls = agent.context.llm_client.chat_completion.call_args_list
    assert len(calls) == 2
    
    # The last call is the Perfect It call
    perfect_it_call_args = calls[1][0][0] # payload
    
    # Assert tools were stripped
    assert "tools" not in perfect_it_call_args
    assert "tool_choice" not in perfect_it_call_args
    assert "Perfection Protocol" in str(perfect_it_call_args["messages"][-1]["content"])

@pytest.mark.asyncio
async def test_tool_hallucination(agent):
    """
    Verify agent handles unknown tools gracefully.
    """
    agent.context.llm_client.chat_completion.side_effect = [
        # Call 1: Hallucinate magic_wand_tool
        {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "call_bad",
            "function": {"name": "magic_wand_tool", "arguments": "{}"}
        }]}}]},
        # Call 2: Agent sees error and finishes
        {"choices": [{"message": {"content": "Oops, I cannot do magic."}}]}
    ]
    
    await agent.handle_chat({"messages": [{"role": "user", "content": "Do magic"}]}, [])
    
    # Access the messages from the LAST call to see if Error was injected
    last_call_args = agent.context.llm_client.chat_completion.call_args_list[1][0][0]
    messages = last_call_args["messages"]
    
    # Look for the tool output message
    error_msg = next((m for m in messages if m.get("role") == "tool" and m.get("name") == "magic_wand_tool"), None)
    
    assert error_msg is not None
    assert "Error: Unknown tool" in error_msg["content"]

@pytest.mark.asyncio
async def test_massive_output_truncation(agent):
    """
    Verify massive stderr output is truncated.
    """
    huge_output = "A" * 40000
    agent.available_tools["execute"].return_value = f"EXIT CODE: 1\nSTDOUT/STDERR:\n{huge_output}"
    
    agent.context.llm_client.chat_completion.side_effect = [
        # Call 1: Run code
        {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "call_huge",
            "function": {"name": "execute", "arguments": "{}"}
        }]}}]},
        # Call 2: Edge node summary
        {"choices": [{"message": {"content": "Output too big."}}]},
        # Call 3: Agent reacts
        {"choices": [{"message": {"content": "Finished."}}]}
    ]
    
    await agent.handle_chat({"messages": [{"role": "user", "content": "Run big output"}]}, [])
    
    last_call_args = agent.context.llm_client.chat_completion.call_args_list[-1][0][0]
    messages = last_call_args["messages"]
    
    tool_msg = next((m for m in messages if m.get("role") == "tool" and m.get("name") == "execute"), None)
    
    assert tool_msg is not None
    assert "EDGE CONDENSED" in tool_msg["content"]
    assert len(tool_msg["content"]) < 30000 # Should be around 24000 + overhead

@pytest.mark.asyncio
async def test_infinite_loop_trap(agent):
    """
    Verify redundancy logic blocks duplicate tool calls.
    """
    # Logic: 
    # Turn 1: Call test_tool -> Success
    # Turn 2: Call test_tool (SAME ARGS) -> Should be blocked with SYSTEM MONITOR message
    
    agent.context.llm_client.chat_completion.side_effect = [
        # Call 1
        {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"arg": "same"}'}
        }]}}]},
        # Call 2: Returns exact same tool call
        {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "call_2",
            "function": {"name": "test_tool", "arguments": '{"arg": "same"}'}
        }]}}]},
        # Call 3: Agent sees block and gives up
        {"choices": [{"message": {"content": "I am stuck."}}]}
    ]
    
    await agent.handle_chat({"messages": [{"role": "user", "content": "Loop"}]}, [])
    
    last_call_args = agent.context.llm_client.chat_completion.call_args_list[2][0][0]
    messages = last_call_args["messages"]
    
    # Find the tool message for call_2
    # It should NOT be the result of the tool, but the SYSTEM MONITOR block
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    
    # The last one should be the blocked one
    blocked_msg = tool_msgs[-1]
    
    assert blocked_msg["name"] == "test_tool"
    assert "SYSTEM MONITOR: ERROR - You already executed this exact tool call" in blocked_msg["content"]
