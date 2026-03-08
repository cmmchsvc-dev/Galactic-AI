
import asyncio
import json
import os
import yaml
import sys
from galactic_core_v2 import GalacticCore
from gateway_v3 import GalacticGateway

async def complex_diagnostic():
    print("Starting Galactic Deep Diagnostic...")
    core = GalacticCore('config.yaml')
    print(f"DEBUG: Core config keys: {list(core.config.keys())}")
    print(f"DEBUG: Providers in config: {list(core.config.get('providers', {}).keys())}")
    # Mock some things if needed, but GalacticCore(config.yaml) should be sufficient
    gateway = GalacticGateway(core)
    
    test_cases = [
        {"provider": "google", "model": "gemini-3.1-flash-lite-preview", "label": "Gemini Native (3.1 Flash Lite)"},
        {"provider": "google", "model": "gemini-2.5-flash", "label": "Gemini Native (2.5 Flash)"},
        {"provider": "openrouter", "model": "google/gemini-3.1-pro-preview", "label": "OpenRouter (Gemini 3.1 Pro)"},
        {"provider": "openrouter", "model": "google/gemini-2.5-flash", "label": "OpenRouter (Gemini 2.5 Flash)"},
        {"provider": "vertex", "model": "gemini-3.1-pro-preview-vertex", "label": "Vertex AI (3.1 Pro)"},
        {"provider": "nvidia", "model": "deepseek-ai/deepseek-v3.2", "label": "Nvidia (DeepSeek V3.2)"},
        {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "label": "Nvidia (Llama 3.3 70B)"},
    ]
    
    messages = [{"role": "user", "content": "Hello, respond with only the word 'SUCCESS' if you get this."}]
    
    results = []
    for tc in test_cases:
        print(f"\nTesting {tc['label']} ({tc['provider']}/{tc['model']})...")
        try:
            # Manually set the model/provider on the gateway's llm object
            gateway.llm.provider = tc['provider']
            gateway.llm.model = tc['model']
            gateway.llm.api_key = gateway._get_provider_api_key(tc['provider'])
            
            # We bypass the start_chat/speak loop and call _call_llm directly
            response = await gateway._call_llm(messages)
            
            if "[ERROR]" in response:
                print(f"  FAILED: {response}")
                results.append((tc['label'], "FAIL", response))
            else:
                print(f"  SUCCESS: {response[:50]}...")
                results.append((tc['label'], "PASS", response[:50]))
        except Exception as e:
            print(f"  CRASHED: {str(e)}")
            results.append((tc['label'], "CRASH", str(e)))

    print("\n" + "="*50)
    print("DIAGNOSTIC SUMMARY")
    print("="*50)
    for label, status, detail in results:
        print(f"{label:30} | {status:6} | {detail}")

if __name__ == "__main__":
    asyncio.run(complex_diagnostic())
