import asyncio
import re
import json
import logging
import signal
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GhostInterface")

app = FastAPI()

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global set of connected websockets
connected_websockets = set()

async def log_streamer():
    """Reads journalctl logs and broadcasts them to connected clients."""
    process = await asyncio.create_subprocess_exec(
        "journalctl", "-u", "ghost-agent.service", "-f", "-o", "cat",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    logger.info("Started journalctl log streamer")

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                # Detect error for reactivity
                is_error = "ERROR" in decoded_line or "Exception" in decoded_line
                
                message = json.dumps({
                    "type": "log",
                    "content": decoded_line,
                    "is_error": is_error
                })
                
                # Broadcast to all connected clients
                to_remove = set()
                for ws in connected_websockets:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        to_remove.add(ws)
                
                for ws in to_remove:
                    connected_websockets.remove(ws)
                    
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(log_streamer())

@app.get("/")
async def get():
    return HTMLResponse(content=(static_dir / "index.html").read_text(), status_code=200)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_websockets.remove(websocket)

@app.post("/api/chat")
async def chat_proxy(request: Request):
    """Proxies chat requests to the Ghost Agent."""
    try:
        body = await request.json()
        async with httpx.AsyncClient() as client:
            # Assuming agent is running on port 8000
            response = await client.post("http://localhost:8000/api/chat", json=body, timeout=600.0)
            return response.json()
    except Exception as e:
        logger.error(f"Chat proxy error: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
