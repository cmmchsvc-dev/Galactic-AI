import torch
from skills.base import GalacticSkill

class GPUOffloader(GalacticSkill):
    """
    Hardware Revolution: Orchestrates multi-GPU workloads.
    - CUDA 0: RTX 5070 Ti (Blackwell) -> Shadow Thinking & Large Models
    - CUDA 1: RTX 3080 (Ampere) -> Memory Embeddings & Vision Offloading
    """
    
    skill_name   = "gpu_offloader"
    display_name = "GPU Hive-Orchestrator"
    version      = "1.0.0"
    author       = "Antigravity"
    description  = "Intelligently routes AI workloads to Blackwell and Ampere silicon."
    category     = "system"
    icon         = "⚡"

    def __init__(self, core):
        super().__init__(core)
        self.device_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
        self.devices = {
            "blackwell": "cuda:0" if self.device_count > 0 else "cpu",
            "ampere":    "cuda:1" if self.device_count > 1 else ("cuda:0" if self.device_count > 0 else "cpu")
        }

    def get_device(self, workload_type="standard", vram_required_gb=2.0):
        """Route workloads dynamically based on VRAM and hardware capability."""
        if self.device_count == 0:
            return "cpu"
            
        def has_vram(device_id, needed_gb):
            try:
                props = torch.cuda.get_device_properties(device_id)
                reserved = torch.cuda.memory_reserved(device_id)
                free = (props.total_memory - reserved) / (1024**3)
                return free >= needed_gb
            except Exception:
                return False

        pref_id = 0 # default blackwell
        if workload_type in ("embeddings", "vision", "vector_search") and self.device_count > 1:
            pref_id = 1
            
        if has_vram(pref_id, vram_required_gb):
            return f"cuda:{pref_id}"
            
        # Fallback to the other GPU if preferred is full
        alt_id = 1 if pref_id == 0 else 0
        if self.device_count > 1 and has_vram(alt_id, vram_required_gb):
            return f"cuda:{alt_id}"
            
        return "cpu" # Out of VRAM fallback

    async def get_gpu_stats(self):
        """Returns live telemetry for the dashboard."""
        stats = []
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            util = 0 # Dummy for now, would use pynvml in production
            stats.append({
                "id": i,
                "name": props.name,
                "mem_used": torch.cuda.memory_allocated(i) / (1024**3),
                "mem_total": props.total_memory / (1024**3),
            })
        return stats

    async def run(self):
        gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
        if gpu_count > 0:
            gpu_names = [f"{torch.cuda.get_device_properties(i).name} (C{i})" for i in range(gpu_count)]
            await self.core.log(f"⚡ GPU Accelerator Online. {' & '.join(gpu_names)} identified.", priority=3)
        else:
            await self.core.log("⚡ GPU Accelerator: No CUDA devices found. CPU mode.", priority=3)
        # Warm up GPUs if needed
