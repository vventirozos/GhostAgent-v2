import datetime
import json
import logging
import os
import contextvars
from typing import Any, Optional

request_id_context = contextvars.ContextVar("request_id", default="SYSTEM")
LOG_TRUNCATE_LIMIT = 40
DEBUG_MODE = False 

class Icons:
    # --- Lifecycle ---
    SYSTEM_BOOT  = "⚡"
    SYSTEM_READY = "🚀"
    SYSTEM_SHUT  = "💤"
    
    # --- Request Flow ---
    REQ_START    = "🎬"
    REQ_DONE     = "🏁"
    REQ_WAIT     = "⏳"

    # --- Brain ---
    BRAIN_THINK  = "💭"
    BRAIN_PLAN   = "📋"
    BRAIN_CTX    = "🧩"
    LLM_ASK      = "🗣️"
    LLM_REPLY    = "🤖"
    
    # --- Specialized Tools ---
    TOOL_SEARCH  = "🌐"
    TOOL_DEEP    = "🔬"
    TOOL_CODE    = "🐍"
    TOOL_SHELL   = "🐚"
    TOOL_FILE_W  = "💾"
    TOOL_FILE_R  = "📖"
    TOOL_FILE_S  = "🔍"
    TOOL_FILE_I  = "👀"
    TOOL_DOWN    = "⬇️"
    
    # --- Memory & Identity ---
    MEM_SAVE     = "📝"
    MEM_READ     = "🔎"
    MEM_MATCH    = "📍"
    MEM_INGEST   = "📚"
    MEM_SPLIT    = "✂️"
    MEM_EMBED    = "🧬"
    MEM_WIPE     = "🧹"
    MEM_SCRATCH  = "🗒️"
    USER_ID      = "👤"
    
    # --- Status ---
    OK           = "✅"
    FAIL         = "❌"
    WARN         = "⚠️"
    STOP         = "🛑"
    RETRY        = "🔄"
    IDEA         = "💡"
    IDEA         = "💡"
    BUG          = "🐛"
    SHIELD       = "🛡️"
    CUT          = "✂️"
    
    # --- Custom Modes ---
    MODE_GHOST   = "🫥"
    POSTGRES     = "🐘"

logger = logging.getLogger("GhostAgent")

def setup_logging(log_file: str, debug: bool = False, daemon: bool = False, verbose: bool = False):
    global DEBUG_MODE, LOG_TRUNCATE_LIMIT
    DEBUG_MODE = debug
    if verbose:
        LOG_TRUNCATE_LIMIT = 1000000
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    if not daemon:
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        sh.setLevel(logging.DEBUG if debug else logging.INFO)
        logger.addHandler(sh)

    for lib in ["httpx", "uvicorn", "docker", "chromadb", "urllib3", "pypdf"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

def pretty_log(title: str, content: Any = None, icon: str = "📝", level: str = "INFO", special_marker: str = None):
    req_id = request_id_context.get()
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")

    if special_marker == "BEGIN":
        print(f"[{level:5}] {Icons.REQ_START} {timestamp} - [{req_id}] {'='*15} REQUEST STARTED {'='*15}", flush=True)
        return
    if special_marker == "END":
        print(f"[{level:5}] {Icons.REQ_DONE} {timestamp} - [{req_id}] {'='*15} REQUEST FINISHED {'='*15}", flush=True)
        return
    if special_marker == "SECTION_START":
        print(f"[{level:5}] {icon} {timestamp} - [{req_id}] {'_'*10} {title} STARTED {'_'*10}", flush=True)
        return
    if special_marker == "SECTION_END":
        print(f"[{level:5}] {icon} {timestamp} - [{req_id}] {'_'*10} {title} ENDED {'_'*12}", flush=True)
        return

    # 1. Title formatting (Upper, fixed width)
    clean_title = title.upper().replace("_", " ")
    header = f"[{level:5}] {icon} {timestamp} - [{req_id}] {clean_title:<25}"
    
    # 2. Content formatting (Strictly single line, truncated)
    if content is None:
        print(header, flush=True)
        return

    if isinstance(content, (dict, list)):
        try: content_str = json.dumps(content, default=str).replace("\n", " ")
        except: content_str = str(content).replace("\n", " ")
    else:
        content_str = str(content).replace("\n", " ").replace("\r", "")

    if len(content_str) > LOG_TRUNCATE_LIMIT:
        content_str = content_str[:LOG_TRUNCATE_LIMIT] + "..."

    print(f"{header} : {content_str}", flush=True)
    
    if DEBUG_MODE:
        logger.debug(f"[{req_id}] {title}: {content}")
