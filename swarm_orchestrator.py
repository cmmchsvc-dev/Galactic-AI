"""
Galactic AI v2.0 — Swarm Orchestrator
Dependency-aware parallel multi-agent execution with a shared blackboard.
Built on gateway.speak_isolated(), which gives every agent contextvar-isolated
LLM/history state — so a whole wave of agents can run concurrently without
corrupting the main session or each other.
"""
import asyncio
import json
import re
import uuid


class SwarmOrchestrator:
    MAX_AGENTS = 8
    AGENT_TIMEOUT = 600          # seconds per agent
    BLACKBOARD_SLICE = 1500      # chars of each finding shared downstream

    KNOWN_PROVIDERS = {"openrouter", "ollama", "nvidia", "groq", "mistral",
                       "anthropic", "google", "openai", "deepseek", "xai"}

    def __init__(self, gateway):
        self.gw = gateway
        self.core = gateway.core

    # ── helpers ──────────────────────────────────────────────

    def _resolve_model(self, role):
        """Map an agent role to (provider, model) from config swarm.role_models,
        falling back to subagents.default_model, then the current main model."""
        cfg = self.core.config.get('swarm', {}) or {}
        target = (cfg.get('role_models', {}) or {}).get(role) \
            or self.core.config.get('subagents', {}).get('default_model')
        if not target:
            return None, None
        t = str(target).strip()
        if '|' in t:
            p, m = t.split('|', 1)
            return p.strip(), m.strip()
        if '/' in t and t.split('/', 1)[0].lower() in self.KNOWN_PROVIDERS:
            p, m = t.split('/', 1)
            return p, m
        return None, t

    async def _decompose(self, goal, max_agents):
        prompt = (
            "Decompose the following goal into specialist sub-tasks for a multi-agent swarm. "
            f"Use AT MOST {max_agents} tasks. Prefer tasks that can run in parallel; only add "
            "'depends_on' when a task truly needs another task's output.\n"
            "Reply with ONLY this JSON, no prose:\n"
            '{"tasks": [{"id": "t1", "role": "researcher|coder|analyst|writer|verifier", '
            '"prompt": "self-contained instruction", "depends_on": []}]}\n\n'
            f"GOAL:\n{goal}"
        )
        raw = await self.gw.speak_isolated(
            prompt, context="You are a swarm task planner. Output only valid JSON.",
            use_lock=False, skip_planning=True, session_id=f"s-swarmplan-{uuid.uuid4().hex[:6]}"
        )
        # Balanced-brace JSON extraction
        text = re.sub(r'<think>.*?</think>', '', str(raw), flags=re.DOTALL)
        start = text.find('{')
        depth = 0
        block = None
        for i in range(start, len(text)) if start >= 0 else []:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    block = text[start:i + 1]
                    break
        if not block:
            return None
        try:
            tasks = json.loads(block, strict=False).get('tasks', [])
        except json.JSONDecodeError:
            return None
        clean = []
        seen = set()
        for t in tasks[:max_agents]:
            tid = str(t.get('id') or f"t{len(clean)+1}")
            if tid in seen or not t.get('prompt'):
                continue
            seen.add(tid)
            clean.append({
                'id': tid,
                'role': str(t.get('role', 'analyst')).lower(),
                'prompt': str(t['prompt']),
                'depends_on': [str(d) for d in (t.get('depends_on') or []) if d],
            })
        return clean or None

    async def _run_agent(self, task, blackboard):
        provider, model = self._resolve_model(task['role'])
        deps_ctx = ""
        for dep in task['depends_on']:
            if dep in blackboard:
                deps_ctx += f"\n[FINDINGS FROM {dep}]:\n{blackboard[dep][:self.BLACKBOARD_SLICE]}\n"
        prompt = task['prompt'] + (
            f"\n\n--- SHARED BLACKBOARD (upstream agent findings) ---{deps_ctx}"
            if deps_ctx else ""
        )
        sid = f"s-swarm-{task['id']}-{uuid.uuid4().hex[:6]}"
        await self.core.log(f"🐝 Swarm agent [{task['id']}/{task['role']}] launched → {task['prompt'][:80]}", priority=2)
        try:
            result = await asyncio.wait_for(
                self.gw.speak_isolated(
                    prompt,
                    context=f"You are a specialist '{task['role']}' agent inside a swarm. "
                            "Be thorough but return ONLY your findings/deliverable — no chit-chat.",
                    override_provider=provider, override_model=model,
                    use_lock=False, skip_planning=True, session_id=sid,
                ),
                timeout=self.AGENT_TIMEOUT,
            )
            return task['id'], str(result)
        except asyncio.TimeoutError:
            return task['id'], f"[FAILED] Agent {task['id']} timed out after {self.AGENT_TIMEOUT}s."
        except Exception as e:
            return task['id'], f"[FAILED] Agent {task['id']} raised: {e}"

    # ── main entry ───────────────────────────────────────────

    async def run(self, goal, max_agents=None):
        max_agents = min(int(max_agents or 4), self.MAX_AGENTS)
        swarm_id = uuid.uuid4().hex[:8]
        await self.core.log(f"🐝 Swarm [{swarm_id}] decomposing goal: {goal[:100]}", priority=1)

        tasks = await self._decompose(goal, max_agents)
        if not tasks:
            return "[ERROR] Swarm planner could not produce a valid task decomposition. Try rephrasing the goal."

        known_ids = {t['id'] for t in tasks}
        for t in tasks:  # drop dangling dependencies so they can't deadlock the DAG
            t['depends_on'] = [d for d in t['depends_on'] if d in known_ids and d != t['id']]

        blackboard = {}
        pending = {t['id']: t for t in tasks}
        wave_num = 0
        while pending:
            ready = [t for t in pending.values() if all(d in blackboard for d in t['depends_on'])]
            if not ready:  # circular dependency — run everything left rather than stall
                ready = list(pending.values())
            wave_num += 1
            await self.core.relay.emit(3, "swarm_update", {
                "swarm_id": swarm_id, "wave": wave_num,
                "running": [t['id'] for t in ready], "done": list(blackboard.keys()),
            })
            await self.core.log(f"🐝 Swarm [{swarm_id}] wave {wave_num}: {len(ready)} agent(s) in parallel", priority=2)
            results = await asyncio.gather(*[self._run_agent(t, blackboard) for t in ready])
            for tid, result in results:
                blackboard[tid] = result
                pending.pop(tid, None)

        digest = "\n\n".join(
            f"### Agent {t['id']} ({t['role']})\nTask: {t['prompt'][:200]}\nResult:\n{blackboard[t['id']][:4000]}"
            for t in tasks
        )
        synthesis = await self.gw.speak_isolated(
            f"Synthesize the swarm results below into ONE coherent final deliverable for this goal:\n"
            f"GOAL: {goal}\n\n{digest}\n\n"
            "Merge findings, resolve contradictions, and clearly flag any [FAILED] agents whose work is missing.",
            context="You are the swarm synthesis coordinator.",
            use_lock=False, skip_planning=True,
            session_id=f"s-swarmsynth-{swarm_id}",
        )
        await self.core.log(f"🐝 Swarm [{swarm_id}] complete: {len(tasks)} agents, {wave_num} wave(s)", priority=1)
        return str(synthesis)
