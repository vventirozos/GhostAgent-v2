# src/ghost_agent/core/agent.py

import asyncio
import datetime
import json
import logging
import uuid
import re
import sys
import gc

import ctypes
import platform
import httpx
from typing import List, Dict, Any, Optional
from pathlib import Path

from .prompts import SYSTEM_PROMPT, CODE_SYSTEM_PROMPT, SMART_MEMORY_PROMPT, PLANNING_SYSTEM_PROMPT, DBA_SYSTEM_PROMPT
from .planning import TaskTree, TaskStatus
from ..utils.logging import Icons, pretty_log, request_id_context
from ..utils.token_counter import estimate_tokens
from ..tools.registry import get_available_tools, TOOL_DEFINITIONS, get_active_tool_definitions
from ..tools.tasks import tool_list_tasks
from ..memory.skills import SkillMemory

logger = logging.getLogger("GhostAgent")

def extract_json_from_text(text: str) -> dict:
    """Safely extracts JSON from LLM outputs, ignoring conversational filler and markdown blocks."""
    import re, json
    try:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
        if match: return json.loads(match.group(1))
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1: return json.loads(text[start:end+1])
        return json.loads(text)
    except Exception:
        return {}

class GhostContext:
    def __init__(self, args, sandbox_dir, memory_dir, tor_proxy):
        self.args = args
        self.sandbox_dir = sandbox_dir
        self.memory_dir = memory_dir
        self.tor_proxy = tor_proxy
        self.llm_client = None
        self.memory_system = None
        self.profile_memory = None
        self.skill_memory = None
        self.scratchpad = None
        self.sandbox_manager = None
        self.scheduler = None
        self.last_activity_time = datetime.datetime.now()
        self.cached_sandbox_state = None

class GhostAgent:
    def __init__(self, context: GhostContext):
        self.context = context
        self.available_tools = get_available_tools(context)
        self.agent_semaphore = asyncio.Semaphore(10)
        self.memory_semaphore = asyncio.Semaphore(1)

    def release_unused_ram(self):
        try:
            gc.collect()
            if platform.system() == "Linux":
                try:
                    libc = ctypes.CDLL("libc.so.6")
                    libc.malloc_trim(0)
                except: pass
        except: pass

    def clear_session(self):
        if hasattr(self.context, 'scratchpad') and self.context.scratchpad:
            self.context.scratchpad.clear()
        self.release_unused_ram()
        return True

    def _prepare_planning_context(self, tools_run_this_turn: List[Dict[str, Any]]) -> str:
        if not tools_run_this_turn:
            return "None (Start of Task)"
        
        outputs = []
        for t in tools_run_this_turn:
            content = str(t.get("content", ""))
            if len(content) > 4000:
                # Keep top 4000 so the Planner actually sees the search matches
                content = content[:4000] + "\n\n... [TRUNCATED: Tool output too long. Showing top results only.]"
            outputs.append(f"Tool [{t.get('name', 'unknown')}]: {content}")
            
        return "\n\n".join(outputs)

    def _get_recent_transcript(self, messages: List[Dict[str, Any]]) -> str:
        recent_transcript = ""
        transcript_msgs = [m for m in messages if m.get("role") in ["user", "assistant", "tool"]][-40:]
        for m in transcript_msgs:
            content = m.get('content') or ""
            role = m['role'].upper()
            if role == "TOOL":
                role = f"TOOL ({m.get('name', 'unknown')})"
            recent_transcript += f"{role}: {content[:500]}\n"
        return recent_transcript

    def process_rolling_window(self, messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        if not messages: return []
        system_msgs = [m for m in messages if m.get("role") == "system"]
        raw_history = [m for m in messages if m.get("role") != "system"]
        
        clean_history = []
        seen_tool_outputs = set()
        
        for msg in reversed(raw_history):
            role = msg.get("role")
            content = str(msg.get("content", ""))
            
            if role == "tool":
                tool_name = msg.get('name', 'unknown')
                fingerprint = f"{tool_name}:{content[:100]}"
                if fingerprint in seen_tool_outputs:
                    continue
                seen_tool_outputs.add(fingerprint)
                
            if role == "assistant":
                lower_content = content.lower()
                if ("memory updated" in lower_content or "memory stored" in lower_content) and len(content) < 100:
                    continue
                
            clean_history.append(msg)
            
        clean_history.reverse()
        compressed_history = []
        msg_count = len(clean_history)
        
        for i, msg in enumerate(clean_history):
            role, content = msg.get("role"), str(msg.get("content", ""))
            if role == "tool" and (msg_count - i) > 4 and len(content) > 4000:
                msg_copy = msg.copy()
                msg_copy["content"] = content[:1000] + "\n... [OLD DATA COMPRESSED] ...\n" + content[-500:]
                compressed_history.append(msg_copy)
            else:
                compressed_history.append(msg)

        current_tokens = sum(estimate_tokens(str(m.get("content", ""))) for m in system_msgs)
        final_history = []
        for msg in reversed(compressed_history):
            msg_tokens = estimate_tokens(str(msg.get("content", "")))
            if current_tokens + msg_tokens > max_tokens: break
            final_history.append(msg)
            current_tokens += msg_tokens
            
        final_history.reverse()
        return system_msgs + final_history

    def _prune_context(self, messages: List[Dict[str, Any]], max_tokens: int = 8000) -> List[Dict[str, Any]]:
        current_tokens = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
        if current_tokens < max_tokens:
            return messages
            
        pretty_log("Context Pruning", f"Reducing context from {current_tokens} to {max_tokens} tokens", icon=Icons.CUT)
        
        system_msgs = [m for m in messages if m.get("role") == "system"]
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        
        base_tokens = sum(estimate_tokens(str(m.get("content", ""))) for m in system_msgs)
        if last_user:
            base_tokens += estimate_tokens(str(last_user.get("content", "")))
            
        remaining_budget = max_tokens - base_tokens - 500
        if remaining_budget < 0:
            if last_user: return system_msgs + [last_user]
            return system_msgs
            
        pruned_history = []
        for m in reversed(messages):
            if m.get("role") == "system": continue
            
            # If this is the last_user, we already reserved its budget. Add it instantly.
            if m == last_user:
                pruned_history.append(m)
                continue
                
            msg_tokens = estimate_tokens(str(m.get("content", "")))
            if remaining_budget - msg_tokens >= 0:
                pruned_history.append(m)
                remaining_budget -= msg_tokens
            else:
                break
                
        final_msgs = list(system_msgs)
        final_msgs.extend(reversed(pruned_history))
        return final_msgs

    async def run_smart_memory_task(self, interaction_context: str, model_name: str, selectivity: float):
        if not self.context.memory_system: return
        async with self.memory_semaphore:
            interaction_context = interaction_context.replace("\r", "")
            ic_lower = interaction_context.lower()
            ic_parts = ic_lower.split("ai:")
            user_msg = ic_parts[0] if len(ic_parts) > 0 else ""
            ai_msg = ic_parts[1] if len(ic_parts) > 1 else ""
            
            summary_triggers = ["summarize", "summary", "recall", "tell me about", "what is", "recap", "forget", "list documents"]
            is_requesting_summary = any(w in user_msg for w in summary_triggers)
            
            if is_requesting_summary and len(ai_msg) > 500:
                return
                
            final_prompt = SMART_MEMORY_PROMPT + f"\n{interaction_context}"
            try:
                payload = {"model": model_name, "messages": [{"role": "user", "content": final_prompt}], "stream": False, "temperature": 0.1, "response_format": {"type": "json_object"}}
                data = await self.context.llm_client.chat_completion(payload, use_worker=True)
                content = data["choices"][0]["message"]["content"]
                result_json = extract_json_from_text(content)
                score, fact, profile_up = float(result_json.get("score", 0.0)), result_json.get("fact", ""), result_json.get("profile_update", None)
                
                fact_lc = fact.lower()
                is_personal = any(w in fact_lc for w in ["user", "me", "my ", " i ", "identity", "preference", "like"])
                is_technical = any(w in fact_lc for w in ["file", "path", "code", "error", "script", "project", "repo", "build", "library", "version"])
                
                if score >= selectivity and fact and len(fact) <= 200 and len(fact) >= 5 and "none" not in fact_lc:
                    if score >= 0.9 and not (is_personal or is_technical):
                        pretty_log("Auto Memory Skip", f"Discarded generic knowledge: {fact}", icon=Icons.STOP)
                        return
                    memory_type = "identity" if (score >= 0.9 and profile_up) else "auto"
                    await asyncio.to_thread(self.context.memory_system.smart_update, fact, memory_type)
                    pretty_log("Auto Memory Store", f"[{score:.2f}] {fact}", icon=Icons.MEM_SAVE)
                    if memory_type == "identity" and self.context.profile_memory:
                        self.context.profile_memory.update(profile_up.get("category", "notes"), profile_up.get("key", "info"), profile_up.get("value", fact))
            except Exception as e: logger.error(f"Smart memory task failed: {e}")

    async def _execute_post_mortem(self, last_user_content: str, tools_run: list, final_ai_content: str, model: str):
        try:
            history_summary = f"User: {last_user_content}\n"
            for t_msg in tools_run[-5:]:
                history_summary += f"Tool {t_msg.get('name', 'unknown')}: {str(t_msg.get('content', ''))[:200]}\n"
                
            learn_prompt = f"### TASK POST-MORTEM\nReview this successful but complex interaction. Did the agent encounter a specific error, hurdle, or mistake that required a unique solution? If so, extract it as a lesson.\n\nHISTORY:\n{history_summary}\n\nFINAL AI: {final_ai_content[:500]}\n\nReturn ONLY a JSON object with 'task', 'mistake', and 'solution'. If no unique lesson is found, return null."
            
            payload = {"model": model, "messages": [{"role": "system", "content": "You are a Meta-Cognitive Analyst."}, {"role": "user", "content": learn_prompt}], "temperature": 0.1, "response_format": {"type": "json_object"}}
            l_data = await self.context.llm_client.chat_completion(payload, use_worker=True)
            l_content = l_data["choices"][0]["message"].get("content", "")
            if l_content and "null" not in l_content.lower():
                l_json = extract_json_from_text(l_content)
                if all(k in l_json for k in ["task", "mistake", "solution"]):
                    self.context.skill_memory.learn_lesson(l_json["task"], l_json["mistake"], l_json["solution"], memory_system=self.context.memory_system)
                    pretty_log("Auto-Learning", "New lesson captured automatically", icon=Icons.IDEA)
        except Exception as e:
            logger.error(f"Post-mortem failed: {e}")

    async def handle_chat(self, body: Dict[str, Any], background_tasks, request_id: Optional[str] = None):
        req_id = request_id or str(uuid.uuid4())[:8]
        token = request_id_context.set(req_id)
        self.context.last_activity_time = datetime.datetime.now()
        
        try:
            async with self.agent_semaphore:
                pretty_log("Request Initialized", special_marker="BEGIN")
                messages, model, stream_response = body.get("messages", []), body.get("model", "Qwen3-4B-Instruct-2507"), body.get("stream", False)
                
                if len(messages) > 500:
                    messages = [m for m in messages if m.get("role") == "system"] + messages[-500:]
                for m in messages:
                    if isinstance(m.get("content"), str): m["content"] = m["content"].replace("\r", "")
                
                last_user_content = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
                lc = last_user_content.lower()
                
                coding_keywords = [r"\bpython\b", r"\bbash\b", r"\bsh\b", r"\bscript\b", r"\bcode\b", r"\bdef\b", r"\bimport\b"]
                coding_actions = [r"\bwrite\b", r"\brun\b", r"\bexecute\b", r"\bdebug\b", r"\bfix\b", r"\bcreate\b", r"\bgenerate\b", r"\bcount\b", r"\bcalculate\b", r"\banalyze\b", r"\bscrape\b", r"\bplot\b", r"\bgraph\b"]
                has_coding_intent = False
                
                if any(re.search(k, lc) for k in coding_keywords):
                    if any(re.search(a, lc) for a in coding_actions): 
                        has_coding_intent = True
                if ".py" in lc or re.search(r'\bscript\b', lc): 
                    has_coding_intent = True
                
                dba_keywords = [r"\bsql\b", r"\bpostgres\b", r"\bpostgresql\b", r"\bpsql\b", r"\bdatabase\b", r"\bpg_stat\b", r"\bexplain analyze\b", r"\bquery\b", r"\bcte\b", r"\brdbms\b", r"\bdba\b", r"\bschema\b", r"\bvacuum\b", r"\bmvcc\b"]
                has_dba_intent = any(re.search(k, lc) for k in dba_keywords)
                
                meta_keywords = [r"\btitle\b", r"\bname this\b", r"\brename\b", r"\bsummary\b", r"\bsummarize\b", r"\bcaption\b", r"\bdescribe\b"]
                is_meta_task = any(re.search(k, lc) for k in meta_keywords)
                if re.match(r'^[\d\s\+\-\*\/\(\)\=\?]+$', lc):
                    has_coding_intent = False
                    
                profile_context = await asyncio.to_thread(self.context.profile_memory.get_context_string) if self.context.profile_memory else ""
                profile_context = profile_context.replace("\r", "")
                
                working_memory_context = ""
                


                base_prompt = SYSTEM_PROMPT.replace("{{PROFILE}}", profile_context)
                if has_dba_intent and not is_meta_task:
                    current_temp = 0.15
                    pretty_log("Mode Switch", "Ghost PostgreSQL DBA Activated", icon=Icons.MODE_GHOST)
                    base_prompt += "\n\n" + DBA_SYSTEM_PROMPT.replace("{{PROFILE}}", profile_context)
                elif has_coding_intent:
                    current_temp = 0.2
                    pretty_log("Mode Switch", "Ghost Python Specialist Activated", icon=Icons.MODE_GHOST)
                    base_prompt += "\n\n" + CODE_SYSTEM_PROMPT.replace("{{PROFILE}}", profile_context)
                else:
                    current_temp = self.context.args.temperature
                    
                base_prompt += working_memory_context
                base_prompt = base_prompt.replace("\r", "")
                
                found_system = False
                for m in messages:
                    if m.get("role") == "system": m["content"] = base_prompt; found_system = True; break
                if not found_system: messages.insert(0, {"role": "system", "content": base_prompt})
                
                if "task" in lc and ("list" in lc or "show" in lc or "what" in lc or "status" in lc):
                     current_tasks = await tool_list_tasks(self.context.scheduler)
                     messages.append({"role": "system", "content": f"SYSTEM DATA DUMP:\n{current_tasks}\n\nINSTRUCTION: The user cannot see the data above. You MUST copy the task list into your **FINAL ANSWER** now."})
                
                is_fact_check = "fact-check" in lc or "verify" in lc
                trivial_triggers = ["who are you", "hello", " hi ", "hey there", "how are you", "what's up", "name is"]
                is_trivial = any(t in last_user_content.lower() for t in trivial_triggers)
                
                
                should_fetch_memory = (
                    not is_fact_check and 
                    not is_trivial and
                    (not has_coding_intent or "remember" in last_user_content or "previous" in last_user_content)
                )
                
                if self.context.memory_system and last_user_content and should_fetch_memory:
                    mem_context = await asyncio.to_thread(self.context.memory_system.search, last_user_content)
                    if mem_context:
                        mem_context = mem_context.replace("\r", "")
                        pretty_log("Memory Context", f"Retrieved for: {last_user_content}", icon=Icons.BRAIN_CTX)
                        messages.insert(1, {"role": "system", "content": f"[MEMORY CONTEXT]:\n{mem_context}"})
                        
                if self.context.skill_memory:
                    playbook = await asyncio.to_thread(self.context.skill_memory.get_playbook_context, query=last_user_content, memory_system=self.context.memory_system)
                    for m in messages:
                        if m.get("role") == "system":
                            m["content"] += f"\n\n{playbook}"
                            break
                            
                messages = self.process_rolling_window(messages, self.context.args.max_context)
                
                final_ai_content, created_time = "", int(datetime.datetime.now().timestamp())
                force_stop, seen_tools, tool_usage, last_was_failure = False, set(), {}, False
                raw_tools_called = set()
                execution_failure_count = 0
                tools_run_this_turn = []
                forget_was_called = False
                thought_content = ""
                was_complex_task = False
                
                task_tree = TaskTree()
                current_plan_json = {}
                
                current_plan_json = {}
                force_final_response = False

                for turn in range(20):


                    if turn > 2: was_complex_task = True
                    if force_stop: break
                    
                    scratch_data = self.context.scratchpad.list_all() if hasattr(self.context, 'scratchpad') else "None."
                    if has_coding_intent:
                        if self.context.cached_sandbox_state is None:
                            from ..tools.file_system import tool_list_files
                            params = {
                                "sandbox_dir": self.context.sandbox_dir, 
                                "memory_system": self.context.memory_system
                            }
                            sandbox_state = await tool_list_files(**params)
                            self.context.cached_sandbox_state = sandbox_state
                        else:
                            sandbox_state = self.context.cached_sandbox_state
                    else:
                        sandbox_state = "N/A"
                    
                    use_plan = getattr(self.context.args, 'use_planning', True)
                    if use_plan and not is_trivial:
                        pretty_log("Reasoning Loop", f"Turn {turn+1} Strategic Analysis...", icon=Icons.BRAIN_PLAN)
                        
                        last_tool_output = self._prepare_planning_context(tools_run_this_turn[-2:])
                        recent_transcript = self._get_recent_transcript(messages)
                            
                        tool_hints = {
                            "system_utility": "weather, time, health",
                            "execute": "python, bash",
                            "postgres_admin": "sql"
                        }
                        available_tools_list = ", ".join([
                            f"{t['function']['name']} ({tool_hints.get(t['function']['name'], 'native tool')})"
                            for t in get_active_tool_definitions(self.context)
                        ])
                        safe_scratch = str(scratch_data)
                        if len(safe_scratch) > 1500: safe_scratch = safe_scratch[:1500] + "\n...[TRUNCATED]"
                        safe_sandbox = str(sandbox_state)
                        if len(safe_sandbox) > 1500: safe_sandbox = safe_sandbox[:1500] + "\n...[TRUNCATED]"

                        planning_prompt = f"""
### CURRENT SITUATION
SCRAPBOOK:
{safe_scratch}
SANDBOX STATE:
{safe_sandbox if has_coding_intent else 'N/A'}
### RECENT CONVERSATION:
{recent_transcript}

User Request: {last_user_content}
Last Tool Output: {last_tool_output}

### AVAILABLE NATIVE TOOLS
[{available_tools_list}]
CRITICAL INSTRUCTION: If an action requires a tool, explicitly name the native JSON tool you intend to use. DO NOT plan to write Python scripts for tasks that have a dedicated native tool. If the user is just asking a question or requesting a code/SQL explanation, set "next_action_id" to "none" and do NOT plan to use a tool.

### TEMPORAL ANCHOR (READ CAREFULLY)
You are currently at TURN {turn+1}. Trust your CURRENT PLAN JSON to know what is already DONE. NEVER revert a 'DONE' task back to 'PENDING'.

### CURRENT PLAN (JSON)
{json.dumps(current_plan_json, indent=2) if current_plan_json else "No plan yet."}
"""
                        planning_payload = {
                            "model": model,
                            "messages": [{"role": "system", "content": PLANNING_SYSTEM_PROMPT}, {"role": "user", "content": planning_prompt}],
                            "temperature": 0.0,
                            "top_p": 0.1,
                            "max_tokens": 1024,
                            "response_format": {"type": "json_object"}
                        }
                        
                        try:
                            p_data = await self.context.llm_client.chat_completion(planning_payload, use_swarm=True)
                            plan_content = p_data["choices"][0]["message"].get("content", "")
                            plan_json = extract_json_from_text(plan_content)
                            
                            thought_content = plan_json.get("thought", "No thought provided.")
                            tree_update = plan_json.get("tree_update", {})
                            next_action_id = plan_json.get("next_action_id", "")
                            required_tool = plan_json.get("required_tool", "all")
                            
                            if tree_update:
                                task_tree.load_from_json(tree_update)
                                current_plan_json = task_tree.to_json()
                                
                            tree_render = task_tree.render()
                            
                            # Planning content is no longer injected into history messages
                            
                            pretty_log("INTERNAL MONOLOGUE", icon=Icons.BRAIN_THINK, special_marker="SECTION_START")
                            pretty_log("Planner Monologue", thought_content, icon=Icons.BRAIN_THINK)
                            pretty_log("INTERNAL MONOLOGUE", icon=Icons.BRAIN_THINK, special_marker="SECTION_END")
                            pretty_log("Reasoning Loop", f"Plan Updated. Focus: {next_action_id}", icon=Icons.OK)
                            
                            if task_tree.root_id and task_tree.nodes[task_tree.root_id].status == TaskStatus.DONE and turn > 0:
                                pretty_log("Finalizing", "Agent signaled completion", icon=Icons.OK)
                                force_stop = True
                        except Exception as e:
                            logger.error(f"Planning step failed: {e}")
                            if not any("### ACTIVE STRATEGY" in m.get("content", "") for m in messages):
                                messages.append({"role": "user", "content": "### ACTIVE STRATEGY: Proceed directly to using a tool. Do NOT provide any conversational response this turn, only output a tool_calls array!"})

                    # Dynamic state no longer mutated via re.sub

                    if last_was_failure:
                        if execution_failure_count == 1:
                            active_temp = max(current_temp, 0.40)
                        elif execution_failure_count >= 2:
                            active_temp = max(current_temp, 0.60)
                        else:
                            active_temp = min(current_temp + 0.1, 0.80)
                        pretty_log("Brainstorming", f"Adjusting variance to {active_temp:.2f} to solve error", icon=Icons.IDEA)
                    else:
                        active_temp = current_temp

                    # Proactive Context Pruning before request
                    messages = self._prune_context(messages, max_tokens=self.context.args.max_context)

                    dynamic_state = f"### DYNAMIC SYSTEM STATE\nCURRENT TIME: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nSCRAPBOOK:\n{scratch_data}\n\n"
                    if has_coding_intent:
                        dynamic_state += f"CURRENT SANDBOX STATE:\n{sandbox_state}\n\n"
                    if use_plan and not is_trivial and 'thought_content' in locals() and thought_content:
                        dynamic_state += f"ACTIVE STRATEGY & PLAN:\nTHOUGHT: {thought_content}\nPLAN:\n{task_tree.render()}\nFOCUS TASK: {next_action_id}\n"
                        
                        if str(next_action_id).strip().lower() == "none":
                            dynamic_state += "CRITICAL INSTRUCTION: DO NOT USE TOOLS this turn. Answer the user directly.\n"
                            force_final_response = True
                        else:
                            dynamic_state += "CRITICAL INSTRUCTION: Execute ONLY the tool required for the FOCUS TASK.\n"

                    req_messages = [m.copy() for m in messages]
                    if req_messages and req_messages[0].get("role") == "system":
                        req_messages[0]["content"] += f"\n\n{dynamic_state.strip()}"
                    else:
                        req_messages.insert(0, {"role": "system", "content": dynamic_state.strip()})

                    payload = {
                        "model": model, 
                        "messages": req_messages, 
                        "stream": False, 
                        "temperature": active_temp, 
                        "max_tokens": 8192
                    }
                    
                    target_tool = locals().get("required_tool", "all")
                    
                    # Dynamic Tool Pruning to accelerate KV-cache prefill
                    if force_final_response or target_tool.lower() == "none":
                        pass # Omit tools array entirely for pure text generation
                    elif target_tool != "all":
                        filtered_tools = [t for t in get_active_tool_definitions(self.context) if t["function"]["name"] == target_tool]
                        payload["tools"] = filtered_tools if filtered_tools else get_active_tool_definitions(self.context)
                        payload["tool_choice"] = "auto"
                    else:
                        payload["tools"] = get_active_tool_definitions(self.context)
                        payload["tool_choice"] = "auto"
                    
                    pretty_log("LLM Request", f"Turn {turn+1} | Temp {active_temp:.2f}", icon=Icons.LLM_ASK)
                    
                    # Ensure msg is always defined in this scope
                    msg = {"role": "assistant", "content": "", "tool_calls": []}
                    try:
                        data = await self.context.llm_client.chat_completion(payload)
                        if "choices" in data and len(data["choices"]) > 0:
                            msg = data["choices"][0]["message"]
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        final_ai_content = "CRITICAL: The upstream LLM server is unreachable. It may have crashed due to memory pressure or is currently restarting. Please wait a moment and try again."
                        pretty_log("System Fault", "Upstream server unreachable", level="ERROR", icon=Icons.FAIL)
                        force_stop = True
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 400 and "context" in e.response.text.lower():
                            pretty_log("Context Overflow", "Emergency pruning triggered...", icon=Icons.WARN)
                            # Emergency Prune: Keep System + Last User + 1 Last Tool Result (Truncated)
                            system_msgs = [m for m in messages if m.get("role") == "system"]
                            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
                            
                            recovery_msgs = system_msgs
                            if last_user: recovery_msgs.append(last_user)
                            
                            # If the last thing was a tool output that caused the overflow, keep it but heavily truncated
                            if tools_run_this_turn:
                                last_tool = tools_run_this_turn[-1]
                                last_tool["content"] = last_tool["content"][:1000] + "\n... [EMERGENCY TRUNCATION] ..."
                                recovery_msgs.append(last_tool)
                                
                            messages = recovery_msgs
                            messages.append({"role": "user", "content": "SYSTEM ALERT: The conversation history was truncated to fit within context limits. Continue task. Assume previous context has been handled."})
                            
                            # RETRY ONCE with pruned context
                            try:
                                payload["messages"] = messages
                                data = await self.context.llm_client.chat_completion(payload)
                                if "choices" in data and len(data["choices"]) > 0:
                                    msg = data["choices"][0]["message"]
                            except Exception as retry_e:
                                final_ai_content = f"CRITICAL: Context overflow recovery failed: {str(retry_e)}"
                                force_stop = True
                                break
                        else:
                            final_ai_content = f"CRITICAL: Upstream error {e.response.status_code}: {e.response.text}"
                            pretty_log("System Fault", f"HTTP {e.response.status_code}", level="ERROR", icon=Icons.FAIL)
                            force_stop = True
                            break
                    except Exception as e:
                        final_ai_content = f"CRITICAL: An unexpected error occurred while communicating with the LLM: {str(e)}"
                        pretty_log("System Fault", str(e), level="ERROR", icon=Icons.FAIL)
                        force_stop = True
                        break

                    content = msg.get("content") or ""
                    tool_calls = list(msg.get("tool_calls") or [])
                    
                    # ---------------------------------------------------------
                    # 🛠️ THE QWEN SYNTAX HEALER & SCRUBBER
                    # ---------------------------------------------------------
                    if "<tool_call>" in content:
                        pretty_log("Syntax Healer", "Intercepted leaked <tool_call> tags. Repairing...", icon=Icons.SHIELD)
                        
                        # Only try to manually parse if the backend completely missed it
                        if not tool_calls:
                            matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content, re.DOTALL | re.IGNORECASE)
                            for match in matches:
                                try:
                                    t_data = extract_json_from_text(match)
                                    if t_data and "name" in t_data:
                                        tool_calls.append({
                                            "id": f"call_{uuid.uuid4().hex[:8]}",
                                            "type": "function",
                                            "function": {
                                                "name": t_data.get("name"),
                                                "arguments": json.dumps(t_data.get("arguments", {}))
                                            }
                                        })
                                except Exception: pass
                                
                        # Radically erase the raw syntax so it doesn't pollute the user's chat output
                        content = re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
                    # ---------------------------------------------------------

                    if content:
                        content = content.replace("\r", "")
                        if final_ai_content and not final_ai_content.endswith("\n\n"):
                            final_ai_content += "\n\n"
                        final_ai_content += content
                        msg["content"] = content
                    else:
                        msg["content"] = ""
                        
                    msg["tool_calls"] = tool_calls
                    
                    if not tool_calls:
                        user_request_context = last_user_content.lower()
                        has_meta_intent = any(kw in user_request_context for kw in ["learn", "skill", "profile", "lesson", "playbook", "record", "save"])
                        meta_tools_called = any(t in raw_tools_called for t in ["learn_skill", "update_profile"])
                        
                        if has_meta_intent and not meta_tools_called and turn < 4:
                            pretty_log("Checklist Nudge", "Enforcing meta-task compliance", icon=Icons.SHIELD)
                            # Remove the recently added content to prevent duplicating text during the loop
                            if content:
                                final_ai_content = final_ai_content[:-len(content)].strip()
                            messages.append({"role": "user", "content": "CRITICAL: You have not fulfilled the learning/profile instructions in the user's request. You MUST call 'learn_skill' or 'update_profile' now before finishing."})
                            continue

                        if self.context.args.smart_memory > 0.0 and last_user_content and not forget_was_called and not last_was_failure:
                            background_tasks.add_task(self.run_smart_memory_task, f"User: {last_user_content}\nAI: {final_ai_content}", model, self.context.args.smart_memory)
                        break
                        
                    messages.append(msg)
                    last_was_failure = False
                    redundancy_strikes = 0
                    
                    tool_tasks, tool_call_metadata = [], []
                    for tool in tool_calls:
                        fname = tool["function"]["name"]
                        raw_tools_called.add(fname)
                        tool_usage[fname] = tool_usage.get(fname, 0) + 1
                        

                            
                        if fname == "forget":
                            forget_was_called = True
                        elif fname == "knowledge_base":
                            try:
                                args = json.loads(tool["function"]["arguments"])
                                if args.get("action") == "forget":
                                    forget_was_called = True
                            except: pass

                        max_uses = 10 if fname in ["deep_research", "web_search"] else (20 if fname == "execute" else 10)
                        if tool_usage[fname] > max_uses:
                            pretty_log("Loop Breaker", f"Halted overuse: {fname}", icon=Icons.STOP)
                            messages.append({"role": "user", "content": f"SYSTEM ALERT: Tool '{fname}' used too many times in a row. It is now blocked. YOU MUST USE A DIFFERENT APPROACH OR STOP."})
                            force_stop = True; break

                        try:
                            t_args = json.loads(tool["function"]["arguments"])
                            
                            is_sandbox_mutation = fname == "execute" or \
                                                  (fname == "file_system" and t_args.get("operation") in ["write", "download", "delete", "move", "rename", "unzip", "git_clone"])
                            
                            if is_sandbox_mutation:
                                self.context.cached_sandbox_state = None

                            a_hash = f"{fname}:{json.dumps(t_args, sort_keys=True)}"
                        except Exception as e:
                            err_msg = {"role": "tool", "tool_call_id": tool["id"], "name": fname, "content": f"Error: Invalid JSON arguments - {str(e)}"}
                            messages.append(err_msg)
                            tools_run_this_turn.append(err_msg)
                            last_was_failure = True
                            continue
                        
                        is_mutating = fname in ["execute", "manage_tasks", "update_profile", "learn_skill"] or \
                                      (fname == "file_system" and t_args.get("operation") in ["write", "download", "delete", "move", "rename"]) or \
                                      (fname == "knowledge_base" and t_args.get("action") in ["ingest_document", "forget", "reset_all", "insert_fact"])

                        if is_mutating:
                            seen_tools.clear()

                        if a_hash in seen_tools and not is_mutating and fname != "system_utility":
                            redundancy_strikes += 1
                            pretty_log("Redundancy", f"Blocked duplicate: {fname}", icon=Icons.RETRY)
                            
                            hint = "Change your strategy."
                            if fname == "recall":
                                hint = "Semantic 'recall' cannot do exact string matching. To find an exact line, use file_system 'search'."
                            elif fname == "web_search":
                                hint = "Try a different search query or use deep_research."
                                
                            err_msg = {"role": "tool", "tool_call_id": tool["id"], "name": fname, "content": f"SYSTEM MONITOR: ERROR - You already executed this exact tool call and it failed to progress the task. DO NOT REPEAT IT. {hint}"}
                            messages.append(err_msg)
                            tools_run_this_turn.append(err_msg)
                            if redundancy_strikes >= 3: force_stop = True
                            continue
                            
                        seen_tools.add(a_hash)
                        
                        if fname == "execute":
                            code_content = t_args.get("content", "")
                            if len(code_content.splitlines()) > 10 and execution_failure_count == 0:

                                
                                pretty_log("Red Team Audit", "Reviewing complex code for destructive risk...", icon=Icons.SHIELD)
                                is_approved, revised_code, critique = await self._run_critic_check(code_content, last_user_content, model)
                                
                                if not is_approved and revised_code:
                                    pretty_log("Red Team Intervention", "Code patched for safety/logic.", icon=Icons.SHIELD)
                                    t_args["content"] = revised_code
                                    tool["function"]["arguments"] = json.dumps(t_args)
                                    messages.append({"role": "user", "content": f"RED TEAM INTERVENTION: Your code was auto-corrected before execution.\nCritique: {critique}\nExecuting patched version."})
                                elif not is_approved:
                                    pretty_log("Red Team Block", f"{critique}", icon=Icons.SHIELD)
                                    err_msg = {"role": "tool", "tool_call_id": tool["id"], "name": fname, "content": f"RED TEAM BLOCK: {critique}. Rewrite the code."}
                                    messages.append(err_msg)
                                    tools_run_this_turn.append(err_msg)
                                    last_was_failure = True
                                    continue

                        if fname in self.available_tools:
                            tool_tasks.append(self.available_tools[fname](**t_args))
                            tool_call_metadata.append((fname, tool["id"], a_hash))
                        else: 
                            err_msg = {"role": "tool", "tool_call_id": tool["id"], "name": fname, "content": f"Error: Unknown tool '{fname}'"}
                            messages.append(err_msg)
                            tools_run_this_turn.append(err_msg)

                    if tool_tasks:
                        results = await asyncio.gather(*tool_tasks, return_exceptions=True)
                        for i, result in enumerate(results):
                            fname, tool_id, a_hash = tool_call_metadata[i]
                            str_res = str(result).replace("\r", "") if not isinstance(result, Exception) else f"Error: {str(result)}"
                            
                            if len(str_res) > 4000 and fname not in ["file_system", "recall", "deep_research", "web_search", "knowledge_base"]:
                                payload = {
                                    "model": model,
                                    "messages": [{"role": "user", "content": f"The user asked: '{last_user_content}'. Summarize this tool output. If it contains facts relevant to the user, extract them. If it is a script error, state the root cause. Output: {str_res[:15000]}"}],
                                    "temperature": 0.0,
                                    "max_tokens": 300
                                }
                                try:
                                    pretty_log("Context Shield", f"Offloading {len(str_res)} chars from {fname} to Edge Worker...", icon=Icons.SHIELD)
                                    summary_data = await self.context.llm_client.chat_completion(payload, use_worker=True)
                                    summary_content = summary_data["choices"][0]["message"].get("content", "").strip()
                                    if summary_content:
                                        str_res = f"[EDGE CONDENSED]: {summary_content}"
                                except Exception:
                                    pass
                                    
                            safe_res = str_res[:12000] + "\n...[TRUNCATED]...\n" + str_res[-12000:] if len(str_res) > 30000 else str_res
                            tool_msg = {"role": "tool", "tool_call_id": tool_id, "name": fname, "content": safe_res}
                            messages.append(tool_msg)
                            tools_run_this_turn.append(tool_msg)
                            
                            if fname == "execute":
                                code_match = re.search(r"EXIT CODE:\s*(\d+)", str_res)
                                if code_match:
                                    exit_code_val = int(code_match.group(1))
                                else:
                                    if "Error" in str_res or "Exception" in str_res or "Traceback" in str_res:
                                        exit_code_val = 1
                                    else:
                                        exit_code_val = 0
                                        
                                if exit_code_val != 0:

                                    execution_failure_count += 1

                                    last_was_failure = True
                                    
                                    error_preview = "Unknown Error"
                                    if "STDOUT/STDERR:" in str_res:
                                        error_preview = str_res.split("STDOUT/STDERR:")[1].strip().replace("\n", " ")
                                    elif "SYSTEM ERROR:" in str_res:
                                        error_preview = str_res.split("SYSTEM ERROR:")[1].strip().split("\n")[0]
                                    else:
                                        error_preview = str_res[:60].replace("\n", " ")
                                        
                                    pretty_log("Execution Fail", f"Strike {execution_failure_count}/3 -> {error_preview}", icon=Icons.FAIL)
                                    from ..tools.file_system import tool_list_files
                                    sandbox_state = await tool_list_files(self.context.sandbox_dir, self.context.memory_system)
                                    messages.append({"role": "user", "content": f"AUTO-DIAGNOSTIC: The script failed with an unexpected error. Try a different approach or fix the bug. Execution details: {str_res}"})
                                    if execution_failure_count >= 3:
                                        pretty_log("Loop Breaker", "Forcing final response", icon=Icons.STOP)
                                        messages.append({"role": "user", "content": "SYSTEM ALERT: You have failed 3 times in a row. The task cannot be completed. Provide a final response explaining the situation."})
                                        force_final_response = True
                                else:
                                    execution_failure_count = 0

                                    pretty_log("Execution Ok", "Script completed with exit code 0", icon=Icons.OK)
                                    request_context = (last_user_content + thought_content).lower()
                                    has_meta_intent = any(kw in request_context for kw in ["learn", "skill", "profile", "lesson", "playbook", "record", "save"])
                                    if not has_meta_intent:
                                        force_stop = True
                                        
                            elif str_res.startswith("Error:") or str_res.startswith("Critical Tool Error"):
                                execution_failure_count += 1
                                last_was_failure = True
                                if not force_stop:
                                    error_preview = str_res.replace("Error:", "").strip()
                                    pretty_log("Tool Warning", f"{fname} -> {error_preview}", icon=Icons.WARN)
                                    if execution_failure_count >= 3:
                                        pretty_log("Loop Breaker", "Too many sequential tool failures.", icon=Icons.STOP)
                                        messages.append({"role": "user", "content": "SYSTEM ALERT: You have failed 3 times in a row. Stop trying this approach and try something completely different."})
                                        force_stop = True
                                    
                            elif fname in ["manage_tasks", "learn_skill", "update_profile"] and "SUCCESS" in str_res.upper():
                                # Let the agent naturally answer the user instead of halting abruptly.
                                pass

                            else:
                                execution_failure_count = 0

                # --- THE "PERFECT IT" PROTOCOL INJECTION ---
                # Only trigger proactive optimization for heavy engineering/research tasks
                heavy_tools_used = any(t.get('name') in ['execute', 'deep_research'] for t in tools_run_this_turn)
                
                if getattr(self.context.args, 'perfect_it', False) and tools_run_this_turn and heavy_tools_used and execution_failure_count == 0 and not last_was_failure and (not final_ai_content or len(final_ai_content) < 50):
                    pretty_log("Perfect It Protocol", "Generating proactive optimization...", icon=Icons.IDEA)
                    perfect_it_prompt = f"Task completed successfully. Final tool output:\n\n{tools_run_this_turn[-1]['content']}\n\n<system_directive>First, succinctly present the tool output/result to the user. Then, based on your Perfection Protocol, analyze the result and proactively suggest one concrete way to optimize, scale, secure, or automate this work further. RESPOND IN PLAIN TEXT ONLY. DO NOT USE TOOLS.</system_directive>"
                    messages.append({"role": "user", "content": perfect_it_prompt})
                    
                    payload["messages"] = messages
                    
                    # 🔴 CRITICAL FIX: Physically remove tools from payload so it cannot hallucinate a tool call
                    if "tools" in payload: del payload["tools"]
                    if "tool_choice" in payload: del payload["tool_choice"]
                    
                    try:
                        perfection_data = await self.context.llm_client.chat_completion(payload, use_worker=True)
                        p_msg = perfection_data["choices"][0]["message"].get("content", "")
                        p_msg = re.sub(r'<tool_call>.*?</tool_call>', '', p_msg, flags=re.DOTALL | re.IGNORECASE).strip()
                        if final_ai_content:
                            final_ai_content += "\n\n" + p_msg
                        else:
                            final_ai_content = p_msg
                    except Exception:
                        if not final_ai_content:
                            final_ai_content = "Task finished successfully, but optimization generation failed."
                elif tools_run_this_turn and not final_ai_content:
                    last_out = tools_run_this_turn[-1].get('content', '')
                    preview = (last_out[:2000] + '\n...[Truncated]') if len(last_out) > 2000 else last_out
                    final_ai_content = f"Process finished successfully.\n\n### Final Output:\n```text\n{preview}\n```"

                # --- FINAL OUTPUT SCRUBBER ---
                final_ai_content = re.sub(r'<tool_call>.*?</tool_call>', '', final_ai_content, flags=re.DOTALL | re.IGNORECASE).strip()
                if not final_ai_content:
                    final_ai_content = "Task executed successfully."

                # --- AUTOMATED POST-MORTEM (AUTO-LEARNING) ---
                if was_complex_task or execution_failure_count > 0:
                    if not force_stop or "READY TO FINALIZE" in thought_content.upper():
                        if background_tasks:
                            background_tasks.add_task(self._execute_post_mortem, last_user_content, list(tools_run_this_turn), final_ai_content, model)

                return final_ai_content, created_time, req_id
                
        finally:
            if 'messages' in locals(): del messages
            if 'tools_run_this_turn' in locals(): del tools_run_this_turn
            if 'sandbox_state' in locals(): del sandbox_state
            if 'data' in locals(): del data
            
            pretty_log("Request Finished", special_marker="END")
            request_id_context.reset(token)

    async def _run_critic_check(self, code: str, task_context: str, model: str):
        from .prompts import CRITIC_SYSTEM_PROMPT
        try:
            prompt = f"### USER TASK:\n{task_context}\n\n### PROPOSED CODE:\n{code}"
            payload = {
                "model": model, 
                "messages": [{"role": "system", "content": CRITIC_SYSTEM_PROMPT}, {"role": "user", "content": prompt}], 
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            data = await self.context.llm_client.chat_completion(payload, use_worker=True)
            content = data["choices"][0]["message"]["content"]
            result = extract_json_from_text(content)
            
            if result.get("status") == "APPROVED":
                return True, None, "Approved"
            else:
                revised_code = result.get("revised_code")
                if revised_code:
                    from ..utils.sanitizer import extract_code_from_markdown
                    revised_code = extract_code_from_markdown(revised_code)
                    
                    # Double-check for leaked backticks or inline code style (if extract failed to strip them)
                    if revised_code.startswith("`") and revised_code.endswith("`"):
                        revised_code = revised_code.strip("`")
                return False, revised_code, result.get("critique", "Unspecified issue")
                
        except Exception as e:
            logger.error(f"Critic failed: {e}")
            return True, None, "Critic Failed (Fail-Open)"
            