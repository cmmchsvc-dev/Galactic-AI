import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from gateway_v3 import GalacticGateway

class MockCore:
    def __init__(self):
        self.config = self._load_config()
        
    def _load_config(self):
        import yaml
        with open(project_root / "config.yaml", "r") as f:
            return yaml.safe_load(f)
            
    async def log(self, msg, priority=1):
        print(f"[{priority}] {msg}")
        
    class Relay:
        async def emit(self, priority, event, data):
            # print(f"RELAY: {event} -> {data}")
            pass
            
    relay = Relay()

async def verify_provider(provider, model):
    print(f"\n--- Verifying {provider} / {model} ---")
    
    # We create a dummy object that looks like GalacticGateway but with minimal imports
    class DummyLLM:
        def __init__(self, p, m):
            self.provider = p
            self.model = m
            self.api_key = "NONE"

    # Patch GalacticGateway to avoid __init__ logic that triggers heavy imports
    original_init = GalacticGateway.__init__
    GalacticGateway.__init__ = lambda self, core: None
    
    core = MockCore()
    gateway = GalacticGateway(core)
    gateway.core = core
    gateway.llm = DummyLLM(provider, model)
    gateway.thinking_level = 'off'
    gateway.tools = []
    
    # Manually attach required methods and patches to skip complex logic
    def _get_provider_base_url(p):
        return core.config.get('providers', {}).get(p, {}).get('baseUrl', '')
    def _get_provider_api_key(p):
        return core.config.get('providers', {}).get(p, {}).get('apiKey', '')
    def _get_max_tokens(default=None): return 4096
    
    # Patch complex methods to return simple values
    async def _dummy_trim(msgs): return msgs
    def _dummy_system(task, active_tools=None, is_coding=False): return "System Prompt"
    def _dummy_active_tools(): return {}

    gateway._get_provider_base_url = _get_provider_base_url
    gateway._get_provider_api_key = _get_provider_api_key
    gateway._get_max_tokens = _get_max_tokens
    gateway._trim_messages = _dummy_trim
    gateway._build_system_prompt = _dummy_system
    gateway._get_active_tools = _dummy_active_tools
    
    messages = [{"role": "user", "content": "Return the word 'OK' if you can read this."}]
    
    try:
        # Use _call_llm directly to test routing + formatting
        result = await gateway._call_llm(messages)
        print(f"Result: {result}")
        if "OK" in result.upper():
            print("✅ SUCCESS")
        else:
            print("⚠️ UNEXPECTED RESULT (but connection worked)")
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    
    await verify_provider(args.provider, args.model)

if __name__ == "__main__":
    asyncio.run(main())
