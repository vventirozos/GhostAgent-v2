import json
import asyncio
import logging
from typing import List, Dict, Any, Optional
import httpx
from ..utils.logging import Icons, pretty_log
from ..utils.helpers import get_utc_timestamp

logger = logging.getLogger("GhostAgent")

class LLMClient:
    def __init__(self, upstream_url: str, tor_proxy: str = None, swarm_nodes: list = None, worker_nodes: list = None, visual_nodes: list = None):
        self.upstream_url = upstream_url
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        
        # Determine if we need to route through Tor
        # If upstream is NOT localhost, we force Tor usage
        proxy_url = None
        if "127.0.0.1" not in upstream_url and "localhost" not in upstream_url and tor_proxy:
            proxy_url = tor_proxy.replace("socks5://", "socks5h://")
            pretty_log("LLM Connection", f"Routing upstream traffic via Tor ({proxy_url})", icon=Icons.SHIELD)

        self.http_client = httpx.AsyncClient(
            base_url=upstream_url, 
            timeout=600.0, 
            limits=limits,
            proxy=proxy_url,
            follow_redirects=True,
            http2=False
        )

        self.swarm_clients = []
        self._swarm_index = 0
        
        if swarm_nodes:
            for node in swarm_nodes:
                client = httpx.AsyncClient(
                    base_url=node["url"], 
                    timeout=600.0, 
                    limits=limits,
                    proxy=proxy_url,
                    follow_redirects=True,
                    http2=False
                )
                self.swarm_clients.append({
                    "client": client,
                    "url": node["url"],
                    "model": node["model"]
                })

        self.worker_clients = []
        self._worker_index = 0
        
        if worker_nodes:
            for node in worker_nodes:
                client = httpx.AsyncClient(
                    base_url=node["url"], 
                    timeout=600.0, 
                    limits=limits,
                    proxy=proxy_url,
                    follow_redirects=True,
                    http2=False
                )
                self.worker_clients.append({
                    "client": client,
                    "url": node["url"],
                    "model": node["model"]
                })

        self.vision_clients = []
        self._vision_index = 0
        
        if visual_nodes:
            for node in visual_nodes:
                client = httpx.AsyncClient(
                    base_url=node["url"], 
                    timeout=600.0, 
                    limits=limits,
                    proxy=proxy_url,
                    follow_redirects=True,
                    http2=False
                )
                self.vision_clients.append({
                    "client": client,
                    "url": node["url"],
                    "model": node["model"]
                })

    async def close(self):
        await self.http_client.aclose()
        for node in getattr(self, 'swarm_clients', []):
            await node["client"].aclose()
        for node in getattr(self, 'worker_clients', []):
            await node["client"].aclose()
        for node in getattr(self, 'vision_clients', []):
            await node["client"].aclose()

    def get_swarm_node(self, target_model: str = None) -> Optional[Dict[str, Any]]:
        if not getattr(self, 'swarm_clients', []):
            return None
            
        if target_model:
            target_lower = target_model.lower()
            for node in self.swarm_clients:
                if target_lower in node["model"].lower():
                    return node
                    
        node = self.swarm_clients[self._swarm_index]
        self._swarm_index = (self._swarm_index + 1) % len(self.swarm_clients)
        return node

    def get_vision_node(self, target_model: str = None) -> Optional[Dict[str, Any]]:
        vision_clients = getattr(self, 'vision_clients', [])
        if not vision_clients:
            return None
            
        if target_model:
            target_lower = target_model.lower()
            for node in vision_clients:
                if target_lower in node["model"].lower():
                    return node
                    
        if not hasattr(self, '_vision_index'):
            self._vision_index = 0
            
        node = vision_clients[self._vision_index]
        self._vision_index = (self._vision_index + 1) % len(vision_clients)
        return node

    def get_worker_node(self, target_model: str = None) -> Optional[Dict[str, Any]]:
        worker_clients = getattr(self, 'worker_clients', [])
        if not worker_clients:
            return None
            
        if target_model:
            target_lower = target_model.lower()
            for node in worker_clients:
                if target_lower in node["model"].lower():
                    return node
                    
        if not hasattr(self, '_worker_index'):
            self._worker_index = 0
            
        node = worker_clients[self._worker_index]
        self._worker_index = (self._worker_index + 1) % len(worker_clients)
        return node

    async def chat_completion(self, payload: Dict[str, Any], use_swarm: bool = False, use_worker: bool = False, use_vision: bool = False) -> Dict[str, Any]:
        """
        Sends a chat completion request to the upstream LLM with robust retry logic.
        """
        if use_vision:
            if getattr(self, 'vision_clients', None):
                target_model = payload.get("model")
                tried_nodes = []
                
                node = self.get_vision_node(target_model)
                
                if node:
                    for _ in range(len(self.vision_clients)):
                        if not node:
                            break
                            
                        if node in tried_nodes:
                            target_model = None
                            node = self.get_vision_node(target_model)
                            
                        loop_breaker = 0
                        while node in tried_nodes and loop_breaker < len(self.vision_clients):
                            node = self.get_vision_node(None)
                            loop_breaker += 1
                            
                        tried_nodes.append(node)
                        
                        pretty_log("Vision Compute", f"Routing request to Vision Node ({node['model']})", level="INFO", icon=Icons.TOOL_DEEP)
                        try:
                            node_payload = payload.copy()
                            node_payload["model"] = node["model"]
                            
                            resp = await node["client"].post("/v1/chat/completions", json=node_payload)
                            resp.raise_for_status()
                            return resp.json()
                        except Exception as e:
                            pretty_log(f"Vision node ({node['model']}) failed: {type(e).__name__}, trying next...", level="WARNING", icon=Icons.WARN)
                            target_model = None
                            node = self.get_vision_node(target_model)
                            continue
                        
                pretty_log("Vision Compute Failed", "All vision nodes failed.", level="ERROR", icon=Icons.WARN)
                
            raise Exception("Vision analysis failed: The dedicated vision node is offline or returned an error, and the main upstream model does not support image inputs.")

        if use_worker and getattr(self, 'worker_clients', None):
            target_model = payload.get("model")
            tried_nodes = []
            
            node = self.get_worker_node(target_model)
            
            if node:
                for _ in range(len(self.worker_clients)):
                    if not node:
                        break
                        
                    if node in tried_nodes:
                        target_model = None
                        node = self.get_worker_node(target_model)
                        
                    loop_breaker = 0
                    while node in tried_nodes and loop_breaker < len(self.worker_clients):
                        node = self.get_worker_node(None)
                        loop_breaker += 1
                        
                    tried_nodes.append(node)
                    
                    pretty_log("Worker Compute", f"Routing background task to Worker Node ({node['model']})", level="INFO", icon="⚙️")
                    try:
                        node_payload = payload.copy()
                        node_payload["model"] = node["model"]
                        
                        resp = await node["client"].post("/v1/chat/completions", json=node_payload)
                        resp.raise_for_status()
                        return resp.json()
                    except Exception as e:
                        pretty_log(f"Worker node ({node['model']}) failed: {type(e).__name__}, trying next...", level="WARNING", icon=Icons.WARN)
                        target_model = None
                        node = self.get_worker_node(target_model)
                        continue
                        
                pretty_log("Worker Compute Failed", "All worker nodes failed, falling back to main upstream", level="WARNING", icon=Icons.WARN)

        elif use_swarm and self.swarm_clients:
            target_model = payload.get("model")
            tried_nodes = []
            
            node = self.get_swarm_node(target_model)
            
            if node:
                for _ in range(len(self.swarm_clients)):
                    if not node:
                        break
                        
                    if node in tried_nodes:
                        target_model = None
                        node = self.get_swarm_node(target_model)
                        
                    loop_breaker = 0
                    while node in tried_nodes and loop_breaker < len(self.swarm_clients):
                        node = self.get_swarm_node(None)
                        loop_breaker += 1
                        
                    tried_nodes.append(node)
                    
                    pretty_log("Edge Compute", f"Routing request to Swarm Node ({node['model']})", level="INFO", icon="⚡")
                    try:
                        node_payload = payload.copy()
                        node_payload["model"] = node["model"]
                        
                        resp = await node["client"].post("/v1/chat/completions", json=node_payload)
                        resp.raise_for_status()
                        return resp.json()
                    except Exception as e:
                        pretty_log(f"Swarm node ({node['model']}) failed: {type(e).__name__}, trying next...", level="WARNING", icon=Icons.WARN)
                        target_model = None
                        node = self.get_swarm_node(target_model)
                        continue
                        
                pretty_log("Edge Compute Failed", "All swarm nodes failed, falling back to main upstream", level="WARNING", icon=Icons.WARN)

        for attempt in range(10): 
            try:
                resp = await self.http_client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                return resp.json()
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
                if attempt < 9:
                    # Exponential backoff: 2, 4, 8, 16... capped at 30s
                    wait_time = min(2 ** (attempt + 1), 30)
                    pretty_log("Upstream Retry", f"[{attempt+1}/10] {type(e).__name__}. Retrying in {wait_time}s...", icon=Icons.RETRY)
                    await asyncio.sleep(wait_time)
                else:
                    pretty_log("Upstream Failed", f"Failed after 10 attempts: {str(e)}", level="ERROR", icon=Icons.FAIL)
                    raise
            except httpx.HTTPStatusError as e:
                pretty_log("Upstream Error", f"HTTP {e.response.status_code}: {e.response.text}", level="ERROR", icon=Icons.FAIL)
                raise
            except Exception as e:
                pretty_log("Upstream Fatal", str(e), level="ERROR", icon=Icons.FAIL)
                raise

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Fetches embeddings from the upstream LLM with robust retry logic.
        """
        payload = {"input": texts, "model": "default"}
        for attempt in range(10): 
            try:
                resp = await self.http_client.post("/v1/embeddings", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError) as e:
                if attempt < 9:
                    wait_time = min(2 ** (attempt + 1), 20)
                    await asyncio.sleep(wait_time)
                else:
                    pretty_log("Embedding Failed", f"Failed after 10 attempts: {str(e)}", level="ERROR", icon=Icons.FAIL)
                    raise
            except Exception as e:
                pretty_log("Embedding Fatal", str(e), level="ERROR", icon=Icons.FAIL)
                raise

    async def stream_openai(self, model: str, content: str, created_time: int, req_id: str):
        chunk_id = f"chatcmpl-{req_id}"
        start_chunk = {
            "id": chunk_id, "object": "chat.completion.chunk", "created": created_time,
            "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(start_chunk)}\n\n".encode('utf-8')

        content_chunk = {
            "id": chunk_id, "object": "chat.completion.chunk", "created": created_time,
            "model": model, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(content_chunk)}\n\n".encode('utf-8')

        stop_chunk = {
            "id": chunk_id, "object": "chat.completion.chunk", "created": created_time,
            "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        }
        yield f"data: {json.dumps(stop_chunk)}\n\n".encode('utf-8')
        yield b"data: [DONE]\n\n"