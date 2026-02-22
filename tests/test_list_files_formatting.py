
import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from ghost_agent.tools.file_system import tool_list_files

@pytest.fixture
def mock_sandbox(tmp_path):
    (tmp_path / "file1.txt").write_text("content")
    (tmp_path / "subdir").mkdir()
    (tmp_path / ".hidden").touch()
    return tmp_path

@pytest.mark.asyncio
async def test_tool_list_files_formatting(mock_sandbox):
    """Test that tool_list_files formats output with trailing slashes for directories."""
    
    # We can run the real function since it uses os.listdir and Path.is_file
    # But we need to ensure the sorting and filtering is correct.
    
    result = await tool_list_files(mock_sandbox)
    
    assert "CURRENT SANDBOX DIRECTORY STRUCTURE:" in result
    
    # Check specific entries
    # Before fix: 📄 file1.txt, 📁 subdir
    # After fix:   file1.txt,   subdir/
    
    # We need to assertions that will FAIL now and PASS after fix.
    
    # The current code produces "📄 file1.txt" and "📁 subdir".
    # The user wants "  file1.txt" and "  subdir/".
    
    # Let's verify the NEW format in this test.
    # If we run this now, it should fail.
    
    assert "  file1.txt" in result
    assert "  subdir/" in result
    
    # Ensure hidden files are skipped
    assert ".hidden" not in result
    
    # Ensure no emojis if user requested removing them (based on the snippet "  {f}")
    assert "📄" not in result
    assert "📁" not in result

