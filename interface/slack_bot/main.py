import os
import re
import json
import logging
import asyncio
import uuid
import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GhostSlackBot")

# Initialize App
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

# Constants
GHOST_API_URL = os.environ.get("GHOST_API_URL", "http://localhost:8000/api/chat")
GHOST_API_KEY = os.environ.get("GHOST_API_KEY", "ghost-secret-123")
SYSTEM_SERVICE_NAME = "ghost-agent.service"

# Emoji Map for Status Updates
EMOJI_MAP = {
    "💭": "Thinking...",
    "📋": "Planning...",
    "🧩": "Recalling Memory...",
    "🗣️": "Asking LLM...",
    "🤖": "LLM Responding...",
    "🌐": "Searching Web...",
    "🔬": "Researching...",
    "🐍": "Writing Code...",
    "🐚": "Running Command...",
    "💾": "Writing File...",
    "📖": "Reading File...",
    "🔍": "Scanning Files...",
    "⬇️": "Downloading...",
    "📝": "Saving Memory...",
    "🔎": "Reading Memory...",
    "✅": "Task Done",
    "❌": "Task Failed",
    "⚠️": "Warning",
    "🛑": "Stopping",
    "🔄": "Retrying...",
    "💡": "Idea!",
    "🎓": "Learning...",
    "🛡️": "Safety Check...",
}

async def tail_logs(request_id: str, say, thread_ts: str):
    """
    Tails journalctl for specific request_id and updates Slack status.
    """
    process = await asyncio.create_subprocess_exec(
        "journalctl", "-u", SYSTEM_SERVICE_NAME, "-f", "-o", "cat",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    current_status_msg = None
    last_emoji = None

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            decoded_line = line.decode('utf-8').strip()
            
            # Filter for our specific request ID
            if f"[{request_id}]" in decoded_line:
                # Extract emoji if present
                found_emoji = None
                for emoji, text in EMOJI_MAP.items():
                    if emoji in decoded_line:
                        found_emoji = emoji
                        status_text = text
                        break
                
                if found_emoji and found_emoji != last_emoji:
                    last_emoji = found_emoji
                    msg_text = f"{found_emoji} {status_text}"
                    
                    if current_status_msg:
                        try:
                            await app.client.chat_update(
                                channel=say.channel,
                                ts=current_status_msg["ts"],
                                text=msg_text
                            )
                        except Exception as e:
                            logger.error(f"Failed to update status: {e}")
                    else:
                        current_status_msg = await say(text=msg_text, thread_ts=thread_ts)

    except asyncio.CancelledError:
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            process.kill()
        # Clean up status message if it exists
        if current_status_msg:
            try:
                await app.client.chat_delete(
                    channel=say.channel,
                    ts=current_status_msg["ts"]
                )
            except: pass

@app.event("app_mention")
async def handle_mention(event, say):
    thread_ts = event.get("thread_ts", event["ts"])
    user_text = re.sub(r"<@.*?>", "", event["text"]).strip()
    
    # Generate ID
    request_id = str(uuid.uuid4())[:8]
    
    # Start Log Tailer
    log_task = asyncio.create_task(tail_logs(request_id, say, thread_ts))
    
    try:
        # Call Ghost Agent API
        async with httpx.AsyncClient(timeout=600.0) as client:
            payload = {
                "messages": [{"role": "user", "content": user_text}],
                "model": "Qwen3-8B-Instruct-2507",
                "stream": False
            }
            headers = {
                "X-Ghost-Key": GHOST_API_KEY,
                "X-Request-ID": request_id
            }
            
            response = await client.post(GHOST_API_URL, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                ai_content = data["choices"][0]["message"]["content"]
                await say(text=ai_content, thread_ts=thread_ts)
            else:
                await say(text=f"Error: Agent returned {response.status_code}", thread_ts=thread_ts)
                
    except Exception as e:
        await say(text=f"System Error: {str(e)}", thread_ts=thread_ts)
    finally:
        log_task.cancel()
        try: await log_task
        except asyncio.CancelledError: pass

async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
