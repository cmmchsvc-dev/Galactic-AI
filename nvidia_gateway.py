"""
Galactic AI - NVIDIA Gateway
Dedicated handler for NVIDIA integrate.api.nvidia.com/v1
Supports: LLMs, Vision (Phi-3.5), Image Generation (SD 3.5 via local NIM)
"""

import httpx
import json
import base64
import asyncio
from pathlib import Path

# ─── NVIDIA Model Registry ────────────────────────────────────────────────────
# Maps friendly names to full NVIDIA catalog model IDs
NVIDIA_MODELS = {
    # ── Frontier LLMs ──
    "llama-405b":     "meta/llama-3.1-405b-instruct",
    "mistral-large":  "mistralai/mistral-large-3-675b-instruct-2512",
    "deepseek-v3":    "deepseek-ai/deepseek-v3.2",
    "qwen-coder":     "qwen/qwen3-coder-480b-a35b-instruct",
    "gemma-27b":      "google/gemma-3-27b-it",
    # ── Vision ──
    "phi-vision":     "microsoft/phi-3.5-vision-instruct",
    # ── Other ──
    "glm5":           "z-ai/glm5",
    "kimi":           "moonshotai/kimi-k2",
    "stepfun":        "stepfun-ai/step-2-16k",
}

# Maps model fragments to their API key name in config.yaml providers.nvidia.keys
KEY_ROUTING = [
    (["llama", "mistral", "gemma", "phi", "microsoft", "meta", "mistralai"],  "deepseek"),  # Use deepseek key as general fallback
    (["qwen"],                                                                  "qwen"),
    (["z-ai", "glm"],                                                           "glm"),
    (["moonshotai", "kimi"],                                                    "kimi"),
    (["stepfun"],                                                               "stepfun"),
    (["deepseek"],                                                              "deepseek"),
]

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def resolve_nvidia_key(model: str, keys: dict) -> str:
    """Pick the right NVIDIA API key for a given model string."""
    model_lower = model.lower()
    for fragments, key_name in KEY_ROUTING:
        if any(frag in model_lower for frag in fragments):
            key = keys.get(key_name)
            if key:
                return key
    # Last resort: return first available key
    all_keys = list(keys.values())
    return all_keys[0] if all_keys else "NONE"


class NvidiaGateway:
    """
    Async client for NVIDIA's OpenAI-compatible API.
    Handles text, vision (multimodal), and streaming.
    """

    def __init__(self, api_key: str, model: str = "meta/llama-3.1-405b-instruct"):
        self.api_key = api_key
        self.model = model
        self.base_url = NVIDIA_BASE_URL
        self.client = httpx.AsyncClient(http2=True, timeout=120.0)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def chat(self, messages: list, max_tokens: int = 2048,
                   temperature: float = 0.7, top_p: float = 0.9) -> str:
        """
        Standard chat completion. messages = [{role, content}, ...]
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }
        try:
            resp = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            data = resp.json()
            if "choices" not in data:
                return f"NVIDIA Error: {json.dumps(data)}"
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"NVIDIA Gateway Error: {str(e)}"

    async def vision(self, prompt: str, image_path: str = None,
                     image_url: str = None, image_b64: str = None,
                     max_tokens: int = 1024) -> str:
        """
        Vision query using phi-3.5-vision-instruct or any vision-capable model.
        Accepts image as file path, URL, or base64 string.
        """
        # Build image content
        if image_path:
            img_bytes = Path(image_path).read_bytes()
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            # Detect mime type
            ext = Path(image_path).suffix.lower()
            mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                    '.png': 'image/png', '.gif': 'image/gif',
                    '.webp': 'image/webp'}.get(ext, 'image/jpeg')
            image_content = {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"}
            }
        elif image_url:
            image_content = {
                "type": "image_url",
                "image_url": {"url": image_url}
            }
        elif image_b64:
            image_content = {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            }
        else:
            # Text-only fallback
            return await self.chat([{"role": "user", "content": prompt}])

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                image_content
            ]
        }]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.7,
            "stream": False,
        }
        try:
            resp = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            data = resp.json()
            if "choices" not in data:
                return f"NVIDIA Vision Error: {json.dumps(data)}"
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"NVIDIA Vision Error: {str(e)}"

    async def stream_chat(self, messages: list, on_chunk=None,
                          max_tokens: int = 2048, temperature: float = 0.7) -> str:
        """
        Streaming chat. Calls on_chunk(text) for each token.
        Returns full assembled response.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        full_response = ""
        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={**self._headers(), "Accept": "text/event-stream"},
                json=payload,
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            full_response += delta
                            if on_chunk:
                                await on_chunk(delta) if asyncio.iscoroutinefunction(on_chunk) else on_chunk(delta)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except Exception as e:
            return f"NVIDIA Stream Error: {str(e)}"
        return full_response

    async def close(self):
        await self.client.aclose()


# ─── Convenience factory ──────────────────────────────────────────────────────

def make_nvidia_gateway(config: dict, model_override: str = None) -> NvidiaGateway:
    """
    Build an NvidiaGateway from galactic config.yaml structure.
    config = full parsed config dict.
    """
    nvidia_cfg = config.get("providers", {}).get("nvidia", {})
    keys = nvidia_cfg.get("keys", {})
    model = model_override or config.get("gateway", {}).get("model", "meta/llama-3.1-405b-instruct")
    api_key = resolve_nvidia_key(model, keys)
    return NvidiaGateway(api_key=api_key, model=model)


# ─── Quick test harness ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import yaml
    import sys

    async def test():
        import sys
        sys.stdout.reconfigure(encoding='utf-8')

        with open("config.yaml", "r") as f:
            cfg = yaml.safe_load(f)

        print("\n=== NVIDIA Gateway Test Suite ===")
        print("=" * 50)

        results = []

        # Test 1: Llama 3.1 405B
        print("\n[1] Testing meta/llama-3.1-405b-instruct...")
        try:
            gw = make_nvidia_gateway(cfg, "meta/llama-3.1-405b-instruct")
            resp = await gw.chat([{"role": "user", "content": "Say 'Galactic AI online!' and nothing else."}],
                                 max_tokens=32)
            print(f"Response: {resp}")
            results.append(("llama-3.1-405b", "PASS" if "error" not in resp.lower() else "FAIL", resp[:80]))
            await gw.close()
        except Exception as e:
            results.append(("llama-3.1-405b", "ERROR", str(e)))

        # Test 2: DeepSeek V3
        print("\n[2] Testing deepseek-ai/deepseek-v3.2...")
        try:
            gw = make_nvidia_gateway(cfg, "deepseek-ai/deepseek-v3.2")
            resp = await gw.chat([{"role": "user", "content": "What is 2+2? One word answer."}],
                                 max_tokens=16)
            print(f"Response: {resp}")
            results.append(("deepseek-v3.2", "PASS" if "error" not in resp.lower() else "FAIL", resp[:80]))
            await gw.close()
        except Exception as e:
            results.append(("deepseek-v3.2", "ERROR", str(e)))

        # Test 3: Phi-3.5 Vision (text-only mode)
        print("\n[3] Testing microsoft/phi-3.5-vision-instruct (text mode)...")
        try:
            gw = make_nvidia_gateway(cfg, "microsoft/phi-3.5-vision-instruct")
            resp = await gw.chat([{"role": "user", "content": "Describe what you can do with images in one sentence."}],
                                 max_tokens=128)
            print(f"Response: {resp[:200]}")
            results.append(("phi-3.5-vision", "PASS" if "error" not in resp.lower() else "FAIL", resp[:80]))
            await gw.close()
        except Exception as e:
            results.append(("phi-3.5-vision", "ERROR", str(e)))

        # Test 4: Gemma 3 27B
        print("\n[4] Testing google/gemma-3-27b-it...")
        try:
            gw = make_nvidia_gateway(cfg, "google/gemma-3-27b-it")
            resp = await gw.chat([{"role": "user", "content": "What's the meaning of life in 10 words?"}],
                                 max_tokens=32)
            print(f"Response: {resp}")
            results.append(("gemma-3-27b", "PASS" if "error" not in resp.lower() else "FAIL", resp[:80]))
            await gw.close()
        except Exception as e:
            results.append(("gemma-3-27b", "ERROR", str(e)))

        # Test 5: Mistral Large 3
        print("\n[5] Testing mistralai/mistral-large-3-675b-instruct-2512...")
        try:
            gw = make_nvidia_gateway(cfg, "mistralai/mistral-large-3-675b-instruct-2512")
            resp = await gw.chat([{"role": "user", "content": "Say 'Mistral online!' and nothing else."}],
                                 max_tokens=16)
            print(f"Response: {resp}")
            results.append(("mistral-large-3", "PASS" if "error" not in resp.lower() else "FAIL", resp[:80]))
            await gw.close()
        except Exception as e:
            results.append(("mistral-large-3", "ERROR", str(e)))

        print("\n" + "=" * 50)
        print("RESULTS SUMMARY:")
        print("=" * 50)
        for model, status, preview in results:
            print(f"  [{status:5}] {model}: {preview[:60]}")
        print("=" * 50)

    asyncio.run(test())
