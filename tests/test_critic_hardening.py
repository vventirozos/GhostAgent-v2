
import pytest
from unittest.mock import AsyncMock, MagicMock
from ghost_agent.core.prompts import CRITIC_SYSTEM_PROMPT
from ghost_agent.core.agent import GhostAgent, GhostContext

def test_critic_system_prompt_has_hardening_rules():
    """Verify that the CRITIC_SYSTEM_PROMPT includes the new hardening rules."""
    
    # Rule 1: No Line Trailing Backslashes
    assert "NO LINE TRAILING BACKSLASHES" in CRITIC_SYSTEM_PROMPT, "Prompt missing NO LINE TRAILING BACKSLASHES rule"
    
    # Rule 2: Markdown Required
    assert "MARKDOWN REQUIRED" in CRITIC_SYSTEM_PROMPT, "Prompt missing MARKDOWN REQUIRED rule"
    assert "MUST wrap the code in ```python blocks" in CRITIC_SYSTEM_PROMPT

    # Rule 3: Python Syntax
    assert "PYTHON SYNTAX" in CRITIC_SYSTEM_PROMPT, "Prompt missing PYTHON SYNTAX rule"

    # Rule 4: String Safety
    assert "STRING SAFETY" in CRITIC_SYSTEM_PROMPT, "Prompt missing STRING SAFETY rule"

    # Rule 5: Conciseness
    assert "CONCISENESS" in CRITIC_SYSTEM_PROMPT, "Prompt missing CONCISENESS rule"

    # Rule 6: Mandatory Revision
    assert "IF YOU FOUND AN ISSUE, YOU MUST POPULATE THIS" in CRITIC_SYSTEM_PROMPT, "Prompt missing MANDATORY REVISION instruction"

@pytest.mark.asyncio
async def test_critic_check_strips_markdown():
    """Verify that _run_critic_check removes markdown blocks from revised code."""
    
    ctx = MagicMock(spec=GhostContext)
    ctx.llm_client = MagicMock()
    # Explicitly set to None to ensure routing to main node (bias isolation)
    ctx.llm_client.coding_clients = None
    ctx.llm_client.worker_clients = None
    # Mock chat_completion to return a revision with markdown
    mock_response = {
        "choices": [{
            "message": {
                "content": '{"status": "REVISED", "critique": "Bad syntax", "revised_code": "```python\\nprint(\'Clean code\')\\n```"}'
            }
        }]
    }
    ctx.llm_client.chat_completion = AsyncMock(return_value=mock_response)
    
    agent = GhostAgent(context=ctx)
    
    # Run the critic check
    is_approved, revised_code, critique = await agent._run_critic_check("original code", "task context", "model-id")
    
    # Assertions
    assert is_approved is False
    assert critique == "Bad syntax"
    # CRITICAL: The markdown backticks and 'python' tag should be gone
    assert "```" not in revised_code
    assert revised_code == "print('Clean code')"

    # Verify that it routes to the MAIN node (bias isolation)
    ctx.llm_client.chat_completion.assert_called_once()
    call_kwargs = ctx.llm_client.chat_completion.call_args.kwargs
    assert not call_kwargs.get("use_worker")
    assert not call_kwargs.get("use_coding")

@pytest.mark.asyncio
async def test_critic_check_fail_open_on_error():
    """Verify that if the critic crashes (e.g. bad JSON), it fails open (returns Approved)."""
    
    ctx = MagicMock(spec=GhostContext)
    ctx.llm_client = MagicMock()
    # Explicitly set to None to ensure routing to main node
    ctx.llm_client.coding_clients = None
    ctx.llm_client.worker_clients = None
    # Mock chat_completion to raise exception
    ctx.llm_client.chat_completion = AsyncMock(side_effect=Exception("LLM Down"))
    
    agent = GhostAgent(context=ctx)
    
    is_approved, revised_code, critique = await agent._run_critic_check("code", "task", "model")
    
    assert is_approved is True
    assert critique == "Critic Failed (Fail-Open)"
    
    # Verify that it still attempted to route to the main node before throwing the error 
    ctx.llm_client.chat_completion.assert_called_once()
    call_kwargs = ctx.llm_client.chat_completion.call_args.kwargs
    assert not call_kwargs.get("use_worker")
    assert not call_kwargs.get("use_coding")
