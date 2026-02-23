import pytest
import os
from unittest.mock import patch, MagicMock
from ghost_agent.utils.token_counter import estimate_tokens

def test_token_counter_lru_cache():
    # 1. Clear the cache at the start of the test
    estimate_tokens.cache_clear()
    
    # 2. Assert initial cache state is completely empty
    initial_info = estimate_tokens.cache_info()
    assert initial_info.hits == 0, "Cache hits should start at 0"
    assert initial_info.misses == 0, "Cache misses should start at 0"
    
    # 3. First run (should be a cache MISS)
    test_text = "This is a predictable string for caching."
    result1 = estimate_tokens(test_text)
    
    first_pass_info = estimate_tokens.cache_info()
    assert first_pass_info.misses == 1, "First evaluation should increment misses"
    assert first_pass_info.hits == 0, "First evaluation should not increment hits"
    
    # 4. Second run (should be a cache HIT)
    result2 = estimate_tokens(test_text)
    
    second_pass_info = estimate_tokens.cache_info()
    assert second_pass_info.hits == 1, "Identical subsequent evaluation should hit the LRU cache"
    assert second_pass_info.misses == 1, "Misses should remain at 1 after a hit"
    assert result1 == result2, "Cache should not alter the deterministic output of the function"
    
    # 5. Clean up
    estimate_tokens.cache_clear()
