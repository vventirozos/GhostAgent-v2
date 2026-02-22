from typing import Dict, Any, List, Callable
from .search import tool_search, tool_deep_research, tool_fact_check
from .database import tool_postgres_admin
from .file_system import tool_file_system
from .tasks import tool_manage_tasks
from .system import tool_system_utility
from .memory import tool_knowledge_base, tool_recall, tool_unified_forget, tool_update_profile, tool_learn_skill, tool_scratchpad
from .execute import tool_execute
from .swarm import tool_delegate_to_swarm

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "delegate_to_swarm",
            "description": "Send MULTIPLE time-consuming tasks to a background cluster of specialized AI workers. Provide an array of tasks. They will run simultaneously and save answers to your SCRAPBOOK.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "instruction": {"type": "string", "description": "Exactly what the swarm worker should do with the data."},
                                "input_data": {"type": "string", "description": "The raw text, URL contents, or data to be processed."},
                                "output_key": {"type": "string", "description": "The Scratchpad key where the result will be saved (e.g., 'api_docs_summary')."},
                                "target_model": {"type": "string", "description": "Optional model name to target a specific swarm node."}
                            },
                            "required": ["instruction", "input_data", "output_key"]
                        },
                        "description": "List of tasks to execute in parallel."
                    }
                },
                "required": ["tasks"]
            }
        }
    },
    {"type": "function", "function": {"name": "system_utility", "description": "MANDATORY for Real-Time Data. Use this to check the current time, perform DIAGNOSTICS/FULL HEALTH CHECK, get user location, or get the weather. You DO NOT have access to these values without this tool.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check_time", "check_weather", "check_health", "check_location"]}, "location": {"type": "string", "description": "Required ONLY for 'check_weather'. Specify the city name (e.g., 'Paris'). Leave empty for local weather."}}, "required": ["action"]}}},
    {
        "type": "function",
        "function": {
            "name": "file_system",
            "description": "Unified file manager. ALWAYS use this to list, read, write, DOWNLOAD, rename, move, or delete files. Do NOT write Python scripts for these tasks. Use operation='search' to find EXACT strings/lines inside a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["read", "read_chunked", "inspect", "search", "list_files", "write", "download", "copy", "rename", "move", "delete"],
                        "description": "The exact operation to perform."
                    },
                    "path": {
                        "type": "string",
                        "description": "The target file or directory path relative to the active project root."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Required when operation='read_chunked'. Specifies the page or section number (1-indexed) to read from a large document or PDF."
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "Optional when operation='read_chunked'. Specifies the size of the text block to extract (default 8000)."
                    },
                    "content": {
                        "type": "string",
                        "description": "For 'write': text to write. For 'search': exact pattern. For 'rename' or 'move': the NEW filename or path."
                    },
                    "url": {
                        "type": "string",
                        "description": "The URL to download (MANDATORY for operation='download')."
                    }
                },
                "required": ["operation", "path"]
            }
        }
    },
    {"type": "function", "function": {"name": "knowledge_base", "description": "Unified memory manager. ALWAYS use this to ingest_document (PDFs/Text), forget, list_docs, or reset_all. Do NOT write Python scripts to read PDFs or ingest files.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["insert_fact", "ingest_document", "forget", "list_docs", "reset_all"]}, "content": {"type": "string", "description": "The target argument. For 'ingest_document', this MUST be the FILENAME or a URL. For 'insert_fact', this is the raw text to memorize. For 'forget', this is the topic."}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "recall", "description": "Search long-term vector memory for general semantic concepts or past conversations. WARNING: This cannot find exact quotes or specific lines. You MUST use file_system operation='search' for exact text matching.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "execute", "description": "Run Python or Shell code. USE THIS ONLY AS A LAST RESORT for custom math, logic, or formatting. DO NOT use this to download files (use file_system), scrape the web, or manage memory. WARNING: Native tools (file_system, knowledge_base) CANNOT be imported in Python. ALWAYS print results.", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "description": "The name of the file to execute. MUST end in .py, .sh, or .js"}, "content": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}, "description": "Optional command line arguments to safely pass to the script."}}, "required": ["filename", "content"]}}},
    {"type": "function", "function": {"name": "learn_skill", "description": "MANDATORY when you solve a complex bug or task after initial failure. Save the lesson so you don't repeat the mistake.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "mistake": {"type": "string"}, "solution": {"type": "string"}}, "required": ["task", "mistake", "solution"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the internet (Anonymous via Tor).", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "deep_research", "description": "Performs deep analysis by searching multiple sources and synthesizing a report.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fact_check", "description": "Verify a claim using deep research and external sources.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "update_profile", "description": "Save a permanent fact about the user (name, preferences, location).", "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "The category for this fact (e.g., 'root', 'preferences', 'projects', 'assets', 'relationships', 'interests')."}, "key": {"type": "string"}, "value": {"type": "string"}}, "required": ["category", "key", "value"]}}},
    {"type": "function", "function": {"name": "manage_tasks", "description": "Consolidated task manager (create, list, stop, stop_all).", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "list", "stop", "stop_all"]}, "task_name": {"type": "string", "description": "A short name for the task (required for 'create')."}, "cron_expression": {"type": "string", "description": "Standard cron format OR 'interval:seconds' (e.g., 'interval:60' for every minute). Required for 'create'."}, "prompt": {"type": "string", "description": "The instruction the background agent should execute (required for 'create')."}, "task_identifier": {"type": "string", "description": "The ID of the task to kill (required for 'stop')."}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "dream_mode", "description": "Triggers Active Memory Consolidation. Use this when the user asks to 'sleep', 'rest', or 'consolidate memories'.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "replan", "description": "Call this tool if your current strategy is failing or if you need to pause and rethink. It forces a fresh planning step.", "parameters": {"type": "object", "properties": {"reason": {"type": "string", "description": "Why are you replanning?"}}, "required": ["reason"]}}},
    {
        "type": "function",
        "function": {
            "name": "scratchpad",
            "description": "Read, write, or clear short-term persistent notes to your SCRAPBOOK. Use this to pass data between turns or tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "get", "list", "clear"]},
                    "key": {"type": "string", "description": "The name of the variable/note (required for set/get)."},
                    "value": {"type": "string", "description": "The content to save (required for set)."}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "postgres_admin",
            "description": "MANDATORY for executing SQL queries, fetching schemas, running EXPLAIN ANALYZE, and checking active queries in a PostgreSQL database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["query", "schema", "explain_analyze", "activity"],
                        "description": "What to do: 'query' (run sql), 'schema' (dump public schema), 'explain_analyze' (run EXPLAIN ANALYZE), 'activity' (check pg_stat_activity)."
                    },
                    "connection_string": {
                        "type": "string",
                        "description": "The PostgreSQL connection URI (e.g., postgresql://user:pass@host:5432/db)."
                    },
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute. Required for 'query' and 'explain_analyze'."
                    },
                    "table_name": {
                        "type": "string",
                        "description": "Optional table name to filter the 'schema' action."
                    }
                },
                "required": ["action", "connection_string"]
            }
        }
    }
]

def get_available_tools(context):
    from .memory import tool_dream_mode # Lazy import to avoid circular dependencies
    return {
        "system_utility": lambda **kwargs: tool_system_utility(tor_proxy=context.tor_proxy, profile_memory=context.profile_memory, context=context, **kwargs),
        "file_system": lambda **kwargs: tool_file_system(sandbox_dir=context.sandbox_dir, tor_proxy=context.tor_proxy, **kwargs),
        "knowledge_base": lambda **kwargs: tool_knowledge_base(sandbox_dir=context.sandbox_dir, memory_system=context.memory_system, profile_memory=context.profile_memory, **kwargs),
        "recall": lambda **kwargs: tool_recall(memory_system=context.memory_system, **kwargs),
        "execute": lambda **kwargs: tool_execute(sandbox_dir=context.sandbox_dir, sandbox_manager=context.sandbox_manager, memory_dir=context.memory_dir, **kwargs),
        "learn_skill": lambda **kwargs: tool_learn_skill(skill_memory=context.skill_memory, memory_system=context.memory_system, **kwargs),
        "web_search": lambda **kwargs: tool_search(anonymous=context.args.anonymous, tor_proxy=context.tor_proxy, **kwargs),
        "deep_research": lambda **kwargs: tool_deep_research(anonymous=context.args.anonymous, tor_proxy=context.tor_proxy, **kwargs),
        "fact_check": lambda **kwargs: tool_fact_check(llm_client=context.llm_client, model_name=context.args.model if hasattr(context.args, 'model') else "Qwen3-4B-Instruct-2507", tool_definitions=TOOL_DEFINITIONS, deep_research_callable=lambda q: tool_deep_research(query=q, anonymous=context.args.anonymous, tor_proxy=context.tor_proxy), **kwargs),
        "update_profile": lambda **kwargs: tool_update_profile(profile_memory=context.profile_memory, memory_system=context.memory_system, **kwargs),
        "scratchpad": lambda **kwargs: tool_scratchpad(scratchpad=context.scratchpad, **kwargs),
        "manage_tasks": lambda **kwargs: tool_manage_tasks(scheduler=context.scheduler, memory_system=context.memory_system, **kwargs),
        "dream_mode": lambda **kwargs: tool_dream_mode(context=context),
        "replan": lambda reason, **kwargs: f"Strategy Reset Triggered. Reason: {reason}\nSYSTEM: The planner will sees this and should update the TaskTree accordingly.",
        "postgres_admin": lambda **kwargs: tool_postgres_admin(**kwargs),
        "delegate_to_swarm": lambda **kwargs: tool_delegate_to_swarm(llm_client=context.llm_client, model_name=getattr(context.args, 'model', 'default'), scratchpad=context.scratchpad, **kwargs)
    }
