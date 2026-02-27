import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from ghost_agent.tools.execute import tool_execute

@pytest.mark.asyncio
async def test_tool_execute_stateful_wrapper():
    """
    Test that the tool_execute properly injects the dill wrapper
    when stateful=True and the file is a python script.
    """
    sandbox_dir = Path("/tmp/workspace")
    sandbox_manager = MagicMock()
    
    # We mock out the actual execution and file operations
    with patch("ghost_agent.tools.execute._get_safe_path") as mock_safe_path, \
         patch("ghost_agent.tools.execute.asyncio.to_thread") as mock_to_thread:
        
        mock_path = MagicMock()
        mock_path.stat.return_value.st_size = 0
        mock_safe_path.return_value = mock_path
        
        # When to_thread is called, we just return (b"output", 0) for the exec call
        async def mock_to_thread_impl(func, *args, **kwargs):
            if func == mock_path.write_text:
                # Capture the content written to the file
                mock_path.written_content = args[0]
                return None
            elif func == mock_path.parent.mkdir:
                return None
            elif func == sandbox_manager.execute:
                return ("output", 0)
            return None
            
        mock_to_thread.side_effect = mock_to_thread_impl
        
        original_code = "x = 10\nprint(x)"
        filename = "test_script.py"
        
        # Call tool_execute with stateful=True
        result = await tool_execute(
            filename=filename,
            content=original_code,
            sandbox_dir=sandbox_dir,
            sandbox_manager=sandbox_manager,
            stateful=True
        )
        
        # Verify the written code includes dill load/dump wrapper
        written_content = mock_path.written_content
        assert "import dill" in written_content
        assert "dill.load_session" in written_content
        assert "dill.dump_session" in written_content
        assert original_code in written_content
        assert "# --- AGENT CODE START ---" in written_content
        assert "# --- AGENT CODE END ---" in written_content
