import os
from pathlib import Path
from transformers import AutoTokenizer
from functools import lru_cache

GRANITE_MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
TOKEN_ENCODER = None

def load_tokenizer(local_tokenizer_path: Path):
    """
    Robust loading strategy: LOCAL DISK -> TOR NETWORK -> FALLBACK
    """
    global TOKEN_ENCODER
    # 1. Try Local Disk (Offline Mode) - PREFERRED
    if local_tokenizer_path.exists() and (local_tokenizer_path / "tokenizer.json").exists():
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            print(f"📂 Loading Tokenizer from local cache: {local_tokenizer_path}")
            TOKEN_ENCODER = AutoTokenizer.from_pretrained(str(local_tokenizer_path), local_files_only=True)
            os.environ.pop("HF_HUB_OFFLINE", None)
            return TOKEN_ENCODER
        except Exception as e:
            os.environ.pop("HF_HUB_OFFLINE", None)
            print(f"⚠️ Local tokenizer corrupted: {e}")

    # 2. Try Network Download (Direct Mode) - FALLBACK
    print(f"⏳ Local missing. Downloading {GRANITE_MODEL_ID} via Direct Network...")
    
    import threading
    import queue

    def _download_hf_tokenizer(q):
        import huggingface_hub
        original_timeout = getattr(huggingface_hub.constants, "HF_HUB_DOWNLOAD_TIMEOUT", 10)
        huggingface_hub.constants.HF_HUB_DOWNLOAD_TIMEOUT = 10
        try:
            enc = AutoTokenizer.from_pretrained(GRANITE_MODEL_ID)
            huggingface_hub.constants.HF_HUB_DOWNLOAD_TIMEOUT = original_timeout
            q.put(("SUCCESS", enc))
        except Exception as err:
            huggingface_hub.constants.HF_HUB_DOWNLOAD_TIMEOUT = original_timeout
            q.put(("ERROR", err))

    q = queue.Queue()
    t = threading.Thread(target=_download_hf_tokenizer, args=(q,), daemon=True)
    t.start()
    
    try:
        status, result = q.get(timeout=15.0)
        if status == "SUCCESS":
            TOKEN_ENCODER = result
        else:
            print(f"❌ Network download failed (Thread Error): {result}")
            return None
            
        # Save it immediately so we never have to download again
        print(f"💾 Caching tokenizer to {local_tokenizer_path}...")
        local_tokenizer_path.mkdir(parents=True, exist_ok=True)
        TOKEN_ENCODER.save_pretrained(str(local_tokenizer_path))
        return TOKEN_ENCODER
        
    except queue.Empty:
        print(f"❌ Network download failed: Hard 15s Timeout Reached. HuggingFace might be blocked (daemon dropped).")
        return None

@lru_cache(maxsize=2048)
def estimate_tokens(text: str) -> int:
    """
    Accurately estimates tokens using the Granite tokenizer.
    Falls back to character approximation if the tokenizer failed to load.
    """
    if not text:
        return 0
        
    # CASE 1: High-Accuracy Granite Tokenizer
    if TOKEN_ENCODER:
        try:
            # Transformers returns a list of input_ids; we just need the count
            return len(TOKEN_ENCODER.encode(text))
        except Exception:
            # Fallback for encoding errors (rare encoding artifacts)
            return len(text) // 3
            
    # CASE 2: Fallback (No tokenizer loaded)
    # Granite models generally average ~3-4 characters per token
    return len(text) // 3
