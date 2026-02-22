# Ghost Agent version 2.0 👻

Ghost Agent is an advanced, autonomous AI service designed for deep reasoning, robust tool execution, and continuous learning. Functioning as a high-tier autonomous software engineer, it is capable of complex operations encompassing full codebase management, internet research, system execution via Docker, and self-correction. The agent has moved to a mac mini m4 16GB the project has been practically rewritten (using antigravity and gemini 3.1) to take advantage of the new hardware. Optionally it is now asynchronously offloading tasks to a jetson nano orin 8GB. All llms (primary, worker, swarm) are loaded using llama-server, the agent's main model is Huihui-Qwen3-4B-Instruct-2507-abliterated.Q8_0.gguf with 65k context window and the secondary LLM on the Nano, that also acts as an Adversarial code critic is running Qwen2.5-Coder-3B-Instruct-abliterated.Q8_0.gguf with 16k context window. Offloading is optional and the Agent, should (theoretically) run on a single Jetson nano 8gb using a Q4 model and 16k context window, although speed is going to suffer... massively.


## Core Capabilities

1. **Autonomous Reasoning & Planning**
    - **Strategic Cortex**: Utilizes a highly constrained JSON-based reasoning loop to plan and track tasks.
    - **Hierarchical TaskTree**: Breaks down complex requests into sub-tasks (Pending, In Progress, Done, Failed).
    - **Strict Anti-Regression**: Employs an immutable 'DONE' status guard to ensure the agent never accidentally reverts completed tasks, solving "Task Amnesia."
    - **Pragmatic Override**: The planner has the authority to safely override flawed user instructions (e.g., using poor search tools when better native ones exist) to guarantee task success.

2. **Advanced Memory Systems**
    - **Profile/Identity System**: Remembers user preferences, project structures, and identity context.
    - **Vector Memory (ChromaDB)**: Ingests, chunks, and semantically retrieves knowledge from PDFs, URLs, and text files.
    - **Smart Memory Auto-Update**: Proactively evaluates conversations to capture personal or project-related facts autonomously.
    - **Skills Library (Auto-Learning)**: Offloaded to a FastAPI background task, the agent automatically runs a post-mortem on complex tasks to extract lessons ("mistakes" and "solutions"), preventing future repeated failures.
    - **Scratchpad**: Ephemeral memory for passing complex variables, huge contexts, or background task results seamlessly between reasoning steps.

3. **Tool & Sandbox Arsenal**
    - **Dockerized Execution (`execute`)**: Safely runs `.py`, `.sh`, and `.js` scripts in an isolated container. Features Syntax Healing (automatically resolving basic syntax/import errors) before execution.
    - **File System Explorer (`file_system`)**: Natively reads, writes, moves, and downloads files. Features robust chunked-read support for traversing massive files without blowing out context windows.
    - **Web & Research (`search`, `knowledge_base`)**: Tor-proxied DuckDuckGo web searches, deep URL content extraction, and document ingestion.
    - **Swarm / Parallel Execution (`delegate_to_swarm`)**: Dispatches heavy, long-running, or highly specific tasks to distributed edge worker nodes. Updates the internal Scratchpad upon completion to allow asynchronous coordination.

4. **Safety & Self-Correction Protocols**
    - **Red Team Critic**: Evaluates generated code for dangerous commands (like `rm -rf /` or `chmod 777`) and prevents execution.
    - **Redundancy Blocker**: Intercepts infinite loops by detecting identical tool calls with identical arguments.
    - **Perfect-It Protocol (Opt-In)**: When activated via the `--perfect-it` CLI argument, the agent proactively reviews its successful executions to suggest performance optimizations or scaling enhancements. 

## System Architecture

### The Agent Loop
The core execution logic resides in `src/ghost_agent/core/agent.py`. For every request:
1. **Context Pruning**: The transcript window is dynamically compressed, retaining up to 40 recent messages to prevent Planner Blindness while adhering to strict context limits.
2. **Strategy Genesis**: The LLM establishes a Hierarchical Task Plan, updating the TaskTree.
3. **Execution**: The agent invokes tools via strict JSON signatures. Native tools are trapped and executed defensively; python code is evaluated in the sandbox.
4. **Critic Validation**: Generated scripts must pass an LLM-based Critic validation to prevent accidental destruction or lazy tool-reinvention.
5. **Auto-Learning**: Concluding a task asynchronously updates the `skill_memory` if a unique friction point was overcome.

### Modularity
* **`main.py`**: Boots the FastAPI service, configures the job scheduler, initializes Sandbox and Memory databases.
* **`llm.py`**: Manages the multi-provider LLM interface.
* **`planning.py`**: Defines the `TaskTree` and `TaskNode` objects to enforce rigid task states.
* **`prompts.py`**: Houses the highly-engineered identity and strict reasoning structures for the Agent, Critic, and Planner models.
* **`sandbox/`**: Manages the Docker socket connections for untrusted code execution.

## Installation & Setup

### Requirements
- Python 3.10+
- Docker (for sandbox execution)
- OpenAI / DeepSeek / Custom VLLM compatible API (configurable)

### Setup
```bash
# Clone the repository
git clone <url> && cd Agent

# Install dependencies
pip install -r requirements.txt

# Set up your environment variables
export GHOST_API_KEY="your-secure-api-key"
export GHOST_MODEL="Qwen3-8B-Instruct-2507" # Configurable across the entire node

# Run the Agent
python src/ghost_agent/main.py --host 0.0.0.0 --port 8000 --perfect-it
```

## CLI Configuration Options
* `--host` / `--port`: API Binding limits.
* `--upstream-url`: The endpoint for your LLM (defaults to high-speed local instance).
* `--model`: Overrides default model selection.
* `--swarm-nodes`: Comma-separated list of secondary LLM instances for map/reduce load balancing.
* `--worker-nodes`: Nodes explicitly dedicated to handling background/edge tasks via `delegate_to_swarm`.
* `--perfect-it`: Enables proactive optimization suggestions after heavy engineering tasks.
* `--anonymous`: Employs Tor & DuckDuckGo proxy routing for web actions.
* `--smart-memory`: Adjusts threshold (0.0 to 1.0) for the automatic persistence of conversational facts.

## Development & Testing
To ensure the integrity of the rigid reasoning and task state protocols, Ghost Agent features an extensive pytest battery encompassing syntax haling, security traps, planner logic, and memory vectorizations.

```bash
# Run the entire test suite
PYTHONPATH=src pytest tests/
```

## Usage
Ghost agent acts natively as a REST API. It is best interfaced via its accompanying GUI, or natively bound to slack (`src/slack_bot/main.py`) where it can act as an omnipresent team DevOps/SRE engineer.