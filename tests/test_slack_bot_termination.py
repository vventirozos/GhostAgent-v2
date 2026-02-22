
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Adjust path to allow importing interface.slack_bot.main
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# We need to mock the imports in main.py before importing it
with patch.dict(sys.modules, {
    "slack_bolt.async_app": MagicMock(),
    "slack_bolt.adapter.socket_mode.async_handler": MagicMock(),
}):
    from interface.slack_bot.main import tail_logs

@pytest.mark.asyncio
async def test_tail_logs_forceful_termination():
    # Mock mocks
    mock_say = AsyncMock()
    
    # Mock process
    mock_process = AsyncMock()
    
    async def readline_side_effect(*args, **kwargs):
        await asyncio.sleep(10)
        return b""
        
    mock_process.stdout.readline.side_effect = readline_side_effect
    
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    
    # Scenario: Process ignores terminate (wait times out)
    # We need to mock asyncio.wait_for to raise TimeoutError
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError) as mock_wait_for:
            
            # Start the task
            task = asyncio.create_task(tail_logs("req-123", mock_say, "thread-1"))
            
            # Allow it to start and reach readline
            await asyncio.sleep(0.1)
            
            # Cancel the task
            task.cancel()
            
            # Wait for task to finish
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            # Verify terminate was called
            mock_process.terminate.assert_called_once()
            
            # Verify wait_for was called with process.wait()
            # Note: wait_for is called inside the exception handler
            assert mock_wait_for.called
            
            # Verify kill was called (because wait_for raised TimeoutError)
            mock_process.kill.assert_called_once()

@pytest.mark.asyncio
async def test_tail_logs_normal_termination():
    # Mock mocks
    mock_say = AsyncMock()
    
    # Mock process
    mock_process = AsyncMock()
    
    async def readline_side_effect(*args, **kwargs):
        await asyncio.sleep(10)
        return b""
        
    mock_process.stdout.readline.side_effect = readline_side_effect
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    
    # Scenario: Process terminates normally within timeout
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        # We don't patch wait_for to fail here, but we can verify it's called
        # Ideally we'd use a spy or just rely on the real wait_for logic not raising exception
        # But wait requires a timeout. We don't want to wait 3s.
        # So we patch wait_for to just await the coroutine immediately (mock success)
        
        async def mock_wait_for_success(coro, timeout):
            await coro
            return
            
        with patch("asyncio.wait_for", side_effect=mock_wait_for_success) as mock_wait_for:
            
            task = asyncio.create_task(tail_logs("req-123", mock_say, "thread-1"))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            mock_process.terminate.assert_called_once()
            # Kill should NOT be called
            mock_process.kill.assert_not_called()
