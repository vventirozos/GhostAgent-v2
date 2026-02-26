import os
import re
import json
import logging
import asyncio
import uuid
import httpx
import sys
import argparse
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
LOG_FILE_PATH = "/Users/vasilis/AI/Logs/ghost-slack-bot-main.err"
GHOST_SANDBOX_DIR = os.environ.get("GHOST_SANDBOX_DIR", "/tmp/sandbox")

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

USER_CACHE = {}

async def get_user_name(user_id: str) -> str:
    if user_id in USER_CACHE:
        return USER_CACHE[user_id]
        
    try:
        user_info = await app.client.users_info(user=user_id)
        if user_info.get("ok"):
            real_name = user_info["user"].get("real_name") or user_info["user"].get("name", "Unknown User")
            USER_CACHE[user_id] = real_name
            return real_name
    except Exception as e:
        logger.error(f"Failed to fetch user info for {user_id}: {e}")
        
    return "Unknown User"

async def download_slack_file(file_info: dict) -> str | None:
    """Downloads a file from Slack to the sandbox directory."""
    url = file_info.get("url_private_download")
    filename = file_info.get("name")
    if not url or not filename:
        return None
        
    os.makedirs(GHOST_SANDBOX_DIR, exist_ok=True)
    filepath = os.path.join(GHOST_SANDBOX_DIR, filename)
    
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {os.environ.get('SLACK_BOT_TOKEN')}"}
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            with open(filepath, "wb") as f:
                f.write(response.content)
            return filename
    except Exception as e:
        logger.error(f"Failed to download file {filename}: {e}")
        return None

async def tail_logs(request_id: str, say, thread_ts: str | None = None):
    """
    Tails the specified log file for specific request_id and updates Slack status.
    """
    current_status_msg = None
    last_emoji = None

    try:
        # Give the system a tiny moment to create the log file if it doesn't exist yet
        while not os.path.exists(LOG_FILE_PATH):
            await asyncio.sleep(0.5)

        with open(LOG_FILE_PATH, 'r') as log_file:
            # Go to the end of the file initially
            log_file.seek(0, os.SEEK_END)
            
            while True:
                line = log_file.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                
                decoded_line = line.strip()
                
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
        # Clean up status message if it exists
        if current_status_msg:
            try:
                await app.client.chat_delete(
                    channel=say.channel,
                    ts=current_status_msg["ts"]
                )
            except: pass

def format_for_slack(text: str) -> str:
    """Translates standard Markdown to Slack's mrkdwn format, ignoring code blocks."""
    parts = re.split(r'(```.*?```|`.*?`)', text, flags=re.DOTALL)
    for i in range(len(parts)):
        if i % 2 == 0:
            # Bold: **text** -> *text*
            parts[i] = re.sub(r'\*\*(.*?)\*\*', r'*\1*', parts[i])
            # Links: [Text](URL) -> <URL|Text>
            parts[i] = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', parts[i])
            # Headers: ### Header -> *Header*
            parts[i] = re.sub(r'^(#{1,6})\s+(.+)$', r'*\2*', parts[i], flags=re.MULTILINE)
    return "".join(parts)

async def _process_message(messages: list, say, thread_ts: str | None = None, event_files: list | None = None):
    # Generate ID
    request_id = str(uuid.uuid4())[:8]
    
    # Start Log Tailer
    log_task = asyncio.create_task(tail_logs(request_id, say, thread_ts))
    
    try:
        # Download files if any
        if event_files:
            for file_info in event_files:
                filename = await download_slack_file(file_info)
                if filename:
                    messages[-1]["content"] += f"\n\n[SYSTEM NOTE: The user attached a file named '{filename}'. It has been downloaded to your sandbox directory. You can use your file_system or knowledge_base tools to interact with it.]"

        # Call Ghost Agent API
        async with httpx.AsyncClient(timeout=600.0) as client:
            payload = {
                "messages": messages,
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
                formatted_content = format_for_slack(ai_content)
                await say(text=formatted_content, thread_ts=thread_ts)
            else:
                await say(text=f"Error: Agent returned {response.status_code}", thread_ts=thread_ts)
                
    except Exception as e:
        await say(text=f"System Error: {str(e)}", thread_ts=thread_ts)
    finally:
        log_task.cancel()
        try: await log_task
        except asyncio.CancelledError: pass

@app.event("app_mention")
async def handle_mention(event, say):
    thread_ts = event.get("thread_ts")
    
    messages = []
    
    if thread_ts:
        try:
            # Fetch thread history
            replies = await app.client.conversations_replies(
                channel=event["channel"],
                ts=thread_ts
            )
            for msg in replies.get("messages", []):
                msg_text = re.sub(r"<@.*?>", "", msg.get("text", "")).strip()
                if not msg_text:
                    continue
                    
                role = "assistant" if msg.get("bot_id") else "user"
                
                if role == "user" and msg.get("user"):
                    real_name = await get_user_name(msg["user"])
                    msg_text = f"[User: {real_name}]: {msg_text}"
                    
                messages.append({"role": role, "content": msg_text})
        except Exception as e:
            logger.error(f"Failed to fetch thread history: {e}")
            
    # Fallback to single message if thread fetch fails or it's not a thread
    if not messages:
        user_text = re.sub(r"<@.*?>", "", event["text"]).strip()
        user_id = event.get("user")
        if user_id:
            real_name = await get_user_name(user_id)
            user_text = f"[User: {real_name}]: {user_text}"
        messages = [{"role": "user", "content": user_text}]
        
    await _process_message(messages, say, thread_ts or event["ts"], event.get("files"))


@app.event("message")
async def handle_direct_message(event, say):
    # Ignore messages that are not direct messages or are from bots
    if event.get("channel_type") != "im" or event.get("bot_id"):
        return
        
    thread_ts = event.get("thread_ts")
    
    messages = []
    
    if thread_ts:
        try:
            replies = await app.client.conversations_replies(
                channel=event["channel"],
                ts=thread_ts
            )
            for msg in replies.get("messages", []):
                msg_text = msg.get("text", "").strip()
                if not msg_text:
                    continue
                    
                role = "assistant" if msg.get("bot_id") else "user"
                
                if role == "user" and msg.get("user"):
                    real_name = await get_user_name(msg["user"])
                    msg_text = f"[User: {real_name}]: {msg_text}"
                    
                messages.append({"role": role, "content": msg_text})
        except Exception as e:
            logger.error(f"Failed to fetch DM thread history: {e}")
            
    if not messages:
        user_text = event.get("text", "").strip()
        if not user_text:
            return
            
        user_id = event.get("user")
        if user_id:
            real_name = await get_user_name(user_id)
            user_text = f"[User: {real_name}]: {user_text}"
        messages = [{"role": "user", "content": user_text}]
        
    await _process_message(messages, say, thread_ts, event.get("files"))

async def main():
    global LOG_FILE_PATH
    parser = argparse.ArgumentParser(description="Ghost Agent Slack Bot")
    parser.add_argument("--log-file", type=str, default="/Users/vasilis/AI/Logs/ghost-slack-bot-main.err", help="Path to the log file to tail")
    args = parser.parse_args()
    
    LOG_FILE_PATH = args.log_file

    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
