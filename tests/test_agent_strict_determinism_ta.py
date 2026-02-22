import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ghost_agent.core.agent import GhostAgent, GhostContext

@pytest.fixture
def agent():
    ctx = MagicMock(spec=GhostContext)
    ctx.args = MagicMock()
    ctx.args.temperature = 0.7
    ctx.args.max_context = 8000
    ctx.args.smart_memory = 0.0
    ctx.llm_client = MagicMock()
    ctx.profile_memory = MagicMock()
    ctx.profile_memory.get_context_string.return_value = ""
    ctx.skill_memory = MagicMock()
    ctx.skill_memory.get_context_string.return_value = ""
    ctx.memory_system = MagicMock()
    ctx.memory_system.search = MagicMock(return_value="")
    ctx.cached_sandbox_state = None
    ctx.sandbox_dir = "/tmp/sandbox"
    agent_inst = GhostAgent(ctx)
    return agent_inst

@pytest.mark.asyncio
async def test_strict_determinism_and_temporal_anchor(agent):
    agent.context.args.use_planning = True
    
    # Mock planning node to return a valid JSON plan
    plan_msg = {"choices": [{"message": {"content": '{"action": "test", "arguments": {}}'}}]}
    final_msg = {"choices": [{"message": {"content": "Final Answer", "tool_calls": []}}]}
    
    agent.context.llm_client.chat_completion = AsyncMock(side_effect=[
        plan_msg, # Planning call
        final_msg # Final response
    ])
    
    body = {"messages": [{"role": "user", "content": "Please write a complex python script to scan the entire network topology and execute it immediately."}], "model": "Qwen-Test"}
    
    await agent.handle_chat(body, background_tasks=MagicMock())
    
    # Check the planning payload
    assert agent.context.llm_client.chat_completion.call_count >= 1
    
    planning_call_args = agent.context.llm_client.chat_completion.call_args_list[0].args[0]
    
    # Verify strict determinism: 0.0 temp, 0.1 top_p
    assert planning_call_args.get("temperature") == 0.0
    assert planning_call_args.get("top_p") == 0.1
    
    # Verify Temporal Anchor
    messages = planning_call_args.get("messages", [])
    prompt_content = ""
    for msg in messages:
        if msg["role"] in ["system", "user"]:
            prompt_content += msg.get("content", "")
            
    assert "### TEMPORAL ANCHOR (READ CAREFULLY)" in prompt_content
    # Since it's the first turn, turn+1 = 1
    assert "TURN 1" in prompt_content
