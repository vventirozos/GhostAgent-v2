import pytest
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

@pytest.fixture
def mock_llm():
    client = MagicMock()
    client.chat_completion = AsyncMock(return_value={
        "choices": [{"message": {"content": "Test Response", "tool_calls": []}}]
    })
    return client

@pytest.fixture
def temp_dirs():
    base = Path(tempfile.mkdtemp())
    sandbox = base / "sandbox"
    memory = base / "memory"
    sandbox.mkdir()
    memory.mkdir()
    yield {"base": base, "sandbox": sandbox, "memory": memory}
    shutil.rmtree(base)

@pytest.fixture
def mock_context(temp_dirs, mock_llm):
    context = MagicMock()
    context.sandbox_dir = temp_dirs["sandbox"]
    context.memory_dir = temp_dirs["memory"]
    context.llm_client = mock_llm
    context.args = MagicMock()
    context.args.anonymous = True
    context.args.max_context = 32768
    context.args.smart_memory = 0.0 # Prevent comparison error
    context.args.verbose = False
    context.args.temperature = 0.1
    
    # Mock return values as strings to prevent TypeErrors in string manipulation
    context.profile_memory = MagicMock()
    context.profile_memory.get_context_string.return_value = "User Profile Data"
    
    context.scratchpad = MagicMock()
    context.scratchpad.list_all.return_value = "Scratchpad Data"
    
    return context
