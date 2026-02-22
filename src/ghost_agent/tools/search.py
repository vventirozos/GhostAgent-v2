import asyncio
import importlib.util
import json
import os
from typing import List, Dict, Any, Callable
from ..utils.logging import Icons, pretty_log
from ..utils.helpers import helper_fetch_url_content

def truncate_query(query: str, limit: int = 35) -> str:
    return (query[:limit] + "..") if len(query) > limit else query

async def tool_search_ddgs(query: str, tor_proxy: str):
    # Ensure proxy is in correct format for ddgs/httpx
    if tor_proxy and "socks5://" in tor_proxy and "socks5h://" not in tor_proxy:
        tor_proxy = tor_proxy.replace("socks5://", "socks5h://")

    # Log with TOR status and truncated query
    pretty_log("DDGS Search", query, icon=Icons.TOOL_SEARCH)
    
    def format_search_results(results: List[Dict]) -> str:
        if not results: return "ERROR: DuckDuckGo returned ZERO results. This usually means the query was too specific or the search engine is blocking the request (CAPTCHA/Tor). TRY A BROADER QUERY."
        formatted = []
        for i, res in enumerate(results, 1):
            title = res.get('title', 'No Title')
            body = res.get('body', res.get('content', 'No content'))
            link = res.get('href', res.get('url', '#'))
            formatted.append(f"### {i}. {title}\n{body}\n[Source: {link}]")
        return "\n\n".join(formatted)

    if not importlib.util.find_spec("ddgs"):
        return "CRITICAL ERROR: 'ddgs' library is missing. Search is impossible."

    from ddgs import DDGS
    from ..utils.helpers import request_new_tor_identity
    for attempt in range(3):
        try:
            def run():
                with DDGS(proxy=tor_proxy, timeout=15) as ddgs:
                    return list(ddgs.text(query, max_results=5))
            raw_results = await asyncio.to_thread(run)
            clean_output = format_search_results(raw_results)
            return clean_output
        except Exception:
            if attempt < 2:
                if tor_proxy:
                    request_new_tor_identity()
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(1)

    return "Error: Search failed after 3 retries."

async def tool_search(query: str, anonymous: bool, tor_proxy: str, **kwargs):
    # Tavily support removed. Always using DDGS.
    return await tool_search_ddgs(query, tor_proxy)

async def tool_deep_research(query: str, anonymous: bool, tor_proxy: str, llm_client=None, model_name="default", **kwargs):
    # Ensure proxy is in correct format for ddgs/httpx
    if tor_proxy and "socks5://" in tor_proxy and "socks5h://" not in tor_proxy:
        tor_proxy = tor_proxy.replace("socks5://", "socks5h://")

    pretty_log("Deep Research", query, icon=Icons.TOOL_DEEP)
    
    urls = []
    
    if not importlib.util.find_spec("ddgs"):
        return "CRITICAL ERROR: 'ddgs' library is missing. Search is impossible."
        
    from ddgs import DDGS
    from ..utils.helpers import request_new_tor_identity
    
    for attempt in range(3):
        try:
            def run():
                with DDGS(proxy=tor_proxy, timeout=15) as ddgs:
                    return list(ddgs.text(query, max_results=10))
            results = await asyncio.to_thread(run)
            
            # FILTER: Skip known junk sites that often appear on Tor blocks
            junk = ["forums.att.com", "reddit.com", "quora.com", "facebook.com", "twitter.com"]
            for r in results:
                url = r.get('href', '').lower()
                if not any(j in url for j in junk):
                    urls.append(r.get('href'))
            # If we filtered everything, just take the first result as a fallback
            if not urls and results:
                urls = [results[0].get('href')]
            # Keep only top 4 high-quality links
            urls = urls[:4]
            break # Success, we have our URLs
        except Exception:
            if attempt < 2:
                if tor_proxy:
                    request_new_tor_identity()
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(1)
            else:
                return f"CRITICAL ERROR: Deep Research search phase failed."

    if not urls: return "ERROR: No search results found. The internet might be blocking your request. Try a different query."

    sem = asyncio.Semaphore(2) 
    async def process_url(url):
        async with sem:
            # Shorten URL for log
            short_url = (url[:35] + "..") if len(url) > 35 else url
            pretty_log("Parsing Data", url, icon=Icons.TOOL_FILE_R)
            text = await helper_fetch_url_content(url)
            if llm_client:
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": f"Extract ONLY the hard facts explicitly relevant to this query: '{query}'. Ignore all other boilerplate. If no relevant info is found, state that.\n\nSource text:\n{text[:15000]}"}],
                    "temperature": 0.0,
                    "max_tokens": 500
                }
                try:
                    summary_data = await llm_client.chat_completion(payload, use_worker=True)
                    pretty_log("Worker Compute", f"Distilling facts from {short_url}", icon=Icons.TOOL_DEEP)
                    preview = "[EDGE EXTRACTED FACTS]:\n" + summary_data["choices"][0]["message"].get("content", "").strip()
                except Exception:
                    preview = text[:3000]
            else:
                preview = text[:3000]
            return f"### SOURCE: {url}\n{preview}\n[...truncated...]\n"

    tasks = [process_url(u) for u in urls]
    page_contents = await asyncio.gather(*tasks)
    full_report = "\n\n".join(page_contents)
    return f"--- DEEP RESEARCH RESULT ---\n{full_report}\n\nSYSTEM INSTRUCTION: Analyze the text above."

async def tool_fact_check(query: str = None, statement: str = None, llm_client=None, tool_definitions=None, deep_research_callable: Callable = None, model_name: str = "Qwen3-8B-Instruct-2507", **kwargs):
    query_text = query or statement or kwargs.get("query") or kwargs.get("statement", "")
    from ..core.agent import extract_json_from_text
    pretty_log("Fact Check", query_text[:50] + "..", icon=Icons.STOP)
    
    allowed_names = ["deep_research"]
    restricted_tools = [t for t in tool_definitions if t["function"]["name"] in allowed_names]
    
    messages = [
        {"role": "system", "content": "### ROLE: DEEP FORENSIC VERIFIER\nVerify this claim with deep_research."},
        {"role": "user", "content": query_text}
    ]
    
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.1,
        "tools": restricted_tools,
        "tool_choice": "auto"
    }
    
    plan_response = await llm_client.chat_completion(payload)
    ai_msg = plan_response["choices"][0]["message"]
    
    if ai_msg.get("tool_calls"):
        t_call = ai_msg["tool_calls"][0]["function"]
        try: t_args = json.loads(t_call["arguments"])
        except: t_args = {}
        
        q = t_args.get("query", query_text)
        dr_result = await deep_research_callable(q)
        messages.append(ai_msg)
        messages.append({"role": "tool", "tool_call_id": ai_msg["tool_calls"][0]["id"], "name": t_call["name"], "content": dr_result})
        
        verify_payload = {"model": model_name, "messages": messages, "temperature": 0.1}
        final_res = await llm_client.chat_completion(verify_payload)
        return f"FACT CHECK COMPLETE:\n{final_res['choices'][0]['message'].get('content', '')}"
    
    return f"FACT CHECK COMPLETE:\n{ai_msg.get('content', 'Fact verified.')}"