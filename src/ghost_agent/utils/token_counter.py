import os
from pathlib import Path
from transformers import AutoTokenizer

GRANITE_MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
TOKEN_ENCODER = None

def load_tokenizer(local_tokenizer_path: Path):
    """
    Robust loading strategy: LOCAL DISK -> TOR NETWORK -> FALLBACK
    """
    global TOKEN_ENCODER
    # 1. Try Local Disk (Offline Mode) - PREFERRED
    if local_tokenizer_path.exists() and (local_tokenizer_path / "tokenizer.json").exists():
        try:
            print(f"📂 Loading Tokenizer from local cache: {local_tokenizer_path}")
            TOKEN_ENCODER = AutoTokenizer.from_pretrained(str(local_tokenizer_path), local_files_only=True)
            return TOKEN_ENCODER
        except Exception as e:
            print(f"⚠️ Local tokenizer corrupted: {e}")

    # 2. Try Network Download (Tor Mode) - FALLBACK
    print(f"⏳ Local missing. Downloading {GRANITE_MODEL_ID} via Tor...")
    
    # Force Remote DNS (socks5h) to prevent leaks and 'Host not found' errors
    tor_proxy = os.getenv("TOR_PROXY", "socks5h://127.0.0.1:9050")
    if tor_proxy.startswith("socks5://"):
        tor_proxy = tor_proxy.replace("socks5://", "socks5h://")
        
    try:
        # We pass proxies explicitly to override any confusing environment vars
        TOKEN_ENCODER = AutoTokenizer.from_pretrained(
            GRANITE_MODEL_ID,
            proxies={"http": tor_proxy, "https": tor_proxy}
        )
        
        # Save it immediately so we never have to download again
        print(f"💾 Caching tokenizer to {local_tokenizer_path}...")
        local_tokenizer_path.mkdir(parents=True, exist_ok=True)
        TOKEN_ENCODER.save_pretrained(str(local_tokenizer_path))
        return TOKEN_ENCODER
        
    except Exception as e:
        print(f"❌ Network download failed: {e}")
        return None

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
