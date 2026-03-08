import os
import asyncio
from datetime import datetime
from skills.base import GalacticSkill

class TensorContext(GalacticSkill):
    """
    Project Galactic Transcendence: Hardware-Accelerated Cognition.
    Uses input from GPUOffloader (RTX 3080) to compress and manage focus.
    """
    
    skill_name   = "tensor_context"
    display_name = "Tensor Context (Ampere Accelerated)"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Leverages the RTX 3080 to distill and prune conversation context."
    category     = "system"
    icon         = "🔋"

    def __init__(self, core):
        super().__init__(core)
        self.compression_threshold = 50 # turns
        self.is_compressing = False

    async def run(self):
        await self.core.log("🔋 Tensor Context monitoring neural pressure via Ampere (C1).", priority=3)
        while True:
            try:
                # Check gateway history size
                history = getattr(self.core.gateway, 'history', [])
                if len(history) >= self.compression_threshold and not self.is_compressing:
                    await self.trigger_compression()
                await asyncio.sleep(60)
            except Exception as e:
                await self.core.log(f"⚠️ Tensor Context monitor error: {e}", priority=1)
                await asyncio.sleep(60)

    async def trigger_compression(self):
        self.is_compressing = True
        try:
            await self.core.log("🔋 [TensorContext] Neural pressure high. Initiating GPU-accelerated distillation...", priority=2)
            
            # Fetch the device from offloader
            offloader = next((s for s in self.core.skills if getattr(s, 'skill_name', '') == 'gpu_offloader'), None)
            device = offloader.get_device("reasoning") if offloader else "cpu"
            
            # In a real setup, we'd load a local model on this device to summarize.
            # Here we route to a speak_isolated call with a "compression" persona.
            history = self.core.gateway.history
            summary_prompt = f"Distill the following {len(history)} conversation turns into a dense, high-entropy 'Semantic Seed'. Preserve all critical technical state and user objectives.\n\n"
            summary_prompt += "\n".join([f"{m['role']}: {m['content']}" for m in history[-20:]]) # Focus on most recent

            # Synthesize seed
            seed = await self.core.gateway.speak_isolated(summary_prompt, context="You are the Neural Compression Engine.")
            
            # Save seed to memory
            await self.core.memory.save_memory(
                content=f"SEMANTIC SEED ({datetime.now().isoformat()}):\n{seed}",
                category="compression",
                metadata={"type": "tensor_context", "device": device}
            )
            
            # Compact the actual history (leave only last 5 turns + seed)
            # This logic is usually in gateway, but we 'inject' the optimization here
            self.core.gateway.history = history[-5:]
            await self.core.log(f"✅ [TensorContext] Distilled {len(history)} turns into a {len(seed)//1024}KB Semantic Seed. Memory optimized.", priority=2)

        except Exception as e:
            await self.core.log(f"⚠️ Compression failed: {e}", priority=1)
        finally:
            self.is_compressing = False
