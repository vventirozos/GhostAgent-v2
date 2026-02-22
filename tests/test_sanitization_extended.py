
import pytest
import re
import json
from unittest.mock import MagicMock, AsyncMock
from ghost_agent.core.agent import GhostAgent, GhostContext
from ghost_agent.utils.sanitizer import sanitize_code

@pytest.fixture
def agent():
    ctx = MagicMock(spec=GhostContext)
    ctx.llm_client = MagicMock()
    return GhostAgent(context=ctx)

async def mock_critic_response(agent, revised_code, status="REVISED"):
    content_obj = {
        "status": status,
        "critique": "Fixed formatting",
        "revised_code": revised_code
    }
    # Mock the LLM return structure
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps(content_obj)
            }
        }]
    }
    agent.context.llm_client.chat_completion = AsyncMock(return_value=mock_response)
    return await agent._run_critic_check("original", "task", "model")

@pytest.mark.asyncio
async def test_critic_strips_indented_markdown(agent):
    # Case: Indented markdown block (The one that caused the bug)
    dirty_code = "  ```python\nprint('Hello')\n  ```"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Hello')"

@pytest.mark.asyncio
async def test_critic_strips_mixed_whitespace_markdown(agent):
    # Case: Tabs and spaces mixed
    dirty_code = "\t```python \nprint('Tabbed')\n\t``` "
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Tabbed')"

@pytest.mark.asyncio
async def test_critic_strips_no_lang_markdown(agent):
    # Case: No language identifier
    dirty_code = "```\nprint('NoLang')\n```"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('NoLang')"

@pytest.mark.asyncio
async def test_critic_strips_inline_code(agent):
    # Case: Inline backticks (sometimes Critic returns this for single lines)
    dirty_code = "`print('Inline')`"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Inline')"

@pytest.mark.asyncio
async def test_critic_strips_complex_indentation(agent):
    # Case: Deeply indented and messy
    # Sanizer regex matches: ```[ \t]*(?:[a-zA-Z]+)?(?:[ \t]*\n|[ \t]+)(.*?)```
    # Input must be a valid block.
    # "    ```   python  \nprint('Deep')\n    ```   "
    dirty_code = "    ```   python  \nprint('Deep')\n    ```   "
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Deep')"

@pytest.mark.asyncio
async def test_critic_strips_no_newline_closing_tag(agent):
    # Case: Closing backticks immediately after code (no newline) but valid block
    dirty_code = "```python\nprint('NoNewline')```"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('NoNewline')"

@pytest.mark.asyncio
async def test_critic_strips_mixed_newline_closing_tag(agent):
    # Case: Newline before opening, no newline before closing
    dirty_code = "```python\nprint('Mixed')```"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Mixed')"

@pytest.mark.asyncio
async def test_critic_strips_conversational_filler(agent):
    # Case: Conversational text before the code block
    dirty_code = "Here is the corrected code:\n```python\nprint('Filler')\n```"
    _, revised, _ = await mock_critic_response(agent, dirty_code)
    assert revised == "print('Filler')"

def test_sanitizer_resilience():
    # Ensure logic in execute.py -> sanitizer.py handles basic python well
    code = "print('Hello')"
    clean, error = sanitize_code(code, "test.py")
    assert clean == "print('Hello')"
    assert error is None

    # Ensure it catches UNFIXABLE syntax errors
    bad_code = "def foo(:" 
    clean, error = sanitize_code(bad_code, "test.py")
    assert error is not None
    assert "SyntaxError" in str(error)
