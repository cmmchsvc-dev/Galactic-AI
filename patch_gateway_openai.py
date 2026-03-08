import os

def patch_gateway_final():
    target_file = r"c:\Users\Chesley\Galactic AI\gateway_v3.py"
    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Correct the global hostname construction
    # Look for the constructed URL parts
    old_hostname = 'host = f"{loc}-aiplatform.googleapis.com"'
    new_hostname = 'host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"'
    
    # 2. Add the special OpenAI endpoint routing logic
    # We want to insert this before the final URL construction
    
    search_marker = 'url = f"https://{host}/v1/projects/{project}/locations/{loc}/publishers/{publisher}/models/{model_id}:streamRawPredict"'
    
    # Replacement for the core of _call_vertex_ai_messages
    openai_logic = """
        # --- MiniMax / OpenAI-compatible Partner Endpoint Fix ---
        if loc == "global" and any(x in model_id.lower() for x in ["minimax", "glm"]):
            host = "aiplatform.googleapis.com"
            # Specific mapping for MiniMax-M2 to the billing model ID
            effective_model = "minimaxai/minimax-m2-maas" if "minimax-m2" in model_id.lower() else model_id
            url = f"https://{host}/v1/projects/{project}/locations/global/endpoints/openapi/chat/completions"
            
            # Payload transformation for OpenAI-compatible endpoint
            payload = {
                "model": effective_model,
                "messages": messages,
                "stream": True,
                "temperature": self.llm.temperature
            }
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            
            # Use specific OpenAI-style call
            try:
                response_text = ""
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code != 200:
                            err_body = await response.aread()
                            return f"[ERROR] Vertex Partner API Error ({response.status_code}): {err_body.decode()}"
                        
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_content = line[6:].strip()
                                if data_content == "[DONE]": break
                                try:
                                    import json
                                    chunk = json.loads(data_content)
                                    if "choices" in chunk and chunk["choices"]:
                                        delta = chunk["choices"][0].get("delta", {})
                                        content_chunk = delta.get("content", "")
                                        if content_chunk:
                                            response_text += content_chunk
                                            yield content_chunk
                                except: pass
                if not response_text: yield "[ERROR] No response from Vertex Partner Endpoint"
                return
            except Exception as e:
                return f"[ERROR] Vertex Partner Endpoint Exception: {str(e)}"
        # --- End OpenAI-compatible Fix ---

        url = f"https://{host}/v1/projects/{project}/locations/{loc}/publishers/{publisher}/models/{model_id}:streamRawPredict"
"""

    if old_hostname in content:
        content = content.replace(old_hostname, new_hostname)
        print("Patched hostname logic.")
    
    if search_marker in content:
        content = content.replace(search_marker, openai_logic)
        print("Patched OpenAI routing logic.")
    else:
        print("Could not find search marker for OpenAI routing.")

    with open(target_file, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patch applied to gateway_v3.py")

if __name__ == "__main__":
    patch_gateway_final()
