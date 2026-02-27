import pytest

def test_prompts_contain_replace_instructions():
    # To avoid importing the main agent loop, we just read the file directly to check
    with open("src/ghost_agent/core/prompts.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "EDITING EXISTING FILES" in content
    assert "NEVER use `file_system` \"write\" (which overwrites the whole file)" in content
    assert "MUST use `file_system` \"replace\"" in content
    assert "exact old block of code in `content` and the new code in `replace_with`" in content
