# src/ghost_agent/core/dream.py

import json
import logging
import asyncio
from typing import List, Dict, Any

from .agent import extract_json_from_text
from ..utils.logging import Icons, pretty_log

logger = logging.getLogger("GhostAgent")

class Dreamer:
    """
    Active Memory Consolidation System.
    "Dreams" about recent memories to synthesize them into higher-order facts and extract heuristics.
    """
    def __init__(self, agent_context):
        self.context = agent_context
        self.memory = agent_context.memory_system

    async def dream(self, model_name: str = "Qwen3-8B-Instruct-2507"):
        if not self.memory or not self.memory.collection:
            return "Memory system not available."
            
        pretty_log("Dream Mode", "Entering REM cycle (Consolidating Memory & Extracting Heuristics)...", icon="💤")
        
        try:
            results = await asyncio.to_thread(
                self.memory.collection.get,
                where={"type": "auto"},
                limit=100,
                include=["documents", "metadatas", "embeddings"]
            )
        except Exception as e:
            return f"Dream error: {e}"
            
        ids = results['ids']
        documents = results['documents']
        
        if len(documents) < 3:
            return "Not enough entropy to dream. (Need > 3 auto-memories to form heuristics)"
            
        mem_list = [f"ID:{i} | {doc}" for i, doc in zip(ids, documents)]
        mem_block = "\n".join(mem_list[:50])
        pretty_log("Dream Mode", f"Analyzing {len(ids)} fragments for meta-patterns...", icon="🧠")
        
        prompt = f"""### IDENTITY
You are the Active Memory Consolidation (Dream) Subsystem.

### TASK
Below is a list of raw, fragmented memories from the Ghost Agent's recent tasks.
Your job is twofold:
1. MERGE overlapping facts into single, high-density facts.
2. EXTRACT HEURISTICS: Identify repeating errors or user preferences and translate them into a persistent behavioral rule (e.g., "Always use absolute paths in Docker").

### RAW MEMORIES
{mem_block}

### OUTPUT FORMAT
Return ONLY valid JSON. If no patterns exist, return empty lists.
{{
  "consolidations": [
    {{
      "synthesis": "The user is working on a Python-based Ghost Agent.",
      "merged_ids": ["ID:...", "ID:..."]
    }}
  ],
  "heuristics": [
    "Always wrap Docker network calls in a try/except."
  ]
}}
"""

        try:
            payload = {
                "model": model_name,
                "messages": [{"role": "system", "content": "You are a Memory Optimizer."}, {"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            data = await self.context.llm_client.chat_completion(payload, use_worker=True)
            content = data["choices"][0]["message"]["content"]
            result = extract_json_from_text(content)
            
            consolidations = result.get("consolidations", [])
            heuristics = result.get("heuristics", [])
            
            if not consolidations and not heuristics:
                return "Dream cycle complete. No patterns or heuristics found."
                
            ops_log = []
            
            # Process Merged Facts
            for item in consolidations:
                synthesis = item.get("synthesis")
                merged_ids = item.get("merged_ids", [])
                stripped_ids = [mid.replace("ID:", "").strip() for mid in merged_ids]
                
                if synthesis and len(stripped_ids) > 1:
                    # ADD new fact
                    await asyncio.to_thread(self.memory.add, synthesis, {"type": "consolidated_fact", "timestamp": "DREAM_CYCLE"})
                    # DELETE old fragments
                    await asyncio.to_thread(self.memory.collection.delete, ids=stripped_ids)
                    ops_log.append(f"Merged {len(stripped_ids)} items -> '{synthesis[:50]}...'")
                    pretty_log("Dream Merge", f"Consolidated {len(stripped_ids)} into 1: {synthesis[:40]}...", icon="✨")

            # Process Heuristics (Save to Skills Playbook)
            if heuristics and self.context.skill_memory:
                for h in heuristics:
                    self.context.skill_memory.learn_lesson(
                        task="Dream Cycle Heuristic Extraction",
                        mistake="Inefficient or sub-optimal execution patterns.",
                        solution=h,
                        memory_system=self.memory
                    )
                    ops_log.append(f"Learned Heuristic: '{h[:50]}...'")
                    pretty_log("Dream Heuristic", f"Extracted Rule: {h[:40]}...", icon="💡")
                    
            summary = "\n".join(ops_log)
            pretty_log("Dream Wake", f"Consolidation Complete:\n{summary}", icon="☀️")
            return f"Dream Complete. Operations:\n{summary}"
            
        except Exception as e:
            return f"Dream failed: {e}"
            