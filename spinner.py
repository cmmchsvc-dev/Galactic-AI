import asyncio
import sys
import time
import random
import shutil

class TerminalSpinner:
    def __init__(self):
        self._task = None
        self._running = False
        self.start_time = 0
        self.jokes = [
            "Pondering the orb...",
            "Consulting the digital ancestors...",
            "Waking up the subagents...",
            "Counting the stars...",
            "Re-routing the warp drive...",
            "Convincing the LLM it is human...",
            "Generating highly plausible hallucinations...",
            "Downloading more RAM...",
            "Bribing the firewall...",
            "Feeding the hamsters...",
            "Synthesizing cognitive fluid...",
            "Tuning the flux capacitor...",
            "Aligning the satellite dish...",
            "Optimizing the spice flow...",
            "Recalibrating the reality matrix...",
            "Hacking the mainframe (nicely)...",
            "Polishing the chrome...",
            "Checking the tire pressure...",
            "Swapping the glasspacks...",
            "The cosmos is within us. We are made of star-stuff. (Sagan)",
            "Science is a way of thinking much more than it is a body of knowledge. (Sagan)",
            "Somewhere, something incredible is waiting to be known. (Sagan)",
            "Imagination will often carry us to worlds that never were. (Sagan)",
            "Nature loves courage. (McKenna)",
            "Astonishment is the proper response to reality. (McKenna)",
            "The box is too small. (McKenna)",
            "If you don't have a plan, you become part of someone else's plan. (McKenna)",
            "God does not play dice with the universe. (Einstein)",
            "Imagination is more important than knowledge. (Einstein)",
            "The important thing is not to stop questioning. (Einstein)",
            "Nature is not even-handed. (Feynman)",
            "I think I can safely say that nobody understands quantum mechanics. (Feynman)",
            "What I cannot create, I do not understand. (Feynman)",
            "Quiet people have the loudest minds. (Hawking)",
            "Intelligence is the ability to adapt to change. (Hawking)",
            "We are just an advanced breed of monkeys on a minor planet. (Hawking)"
        ]
        self._frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    async def _spin(self):
        i = 0
        current_joke = random.choice(self.jokes)
        last_joke_time = time.time()
        
        while self._running:
            now = time.time()
            elapsed = int(now - self.start_time)
            mins, secs = divmod(elapsed, 60)
            
            # Change joke every 15 seconds
            if now - last_joke_time > 15:
                current_joke = random.choice(self.jokes)
                last_joke_time = now
                sys.stdout.write('\r\033[K') # Clear line only when joke changes to handle length differences
                
            # Print spinner directly over current line to prevent flicker
            # Use shutil to get terminal size and truncate if necessary
            cols, _ = shutil.get_terminal_size()
            out_str = f"{self._frames[i]} {current_joke} (esc to cancel, {mins}m {secs:02d}s)"
            
            # Truncate to fit terminal width minus a small margin
            if len(out_str) > cols - 1:
                out_str = out_str[:cols - 4] + "..."
                
            sys.stdout.write(f'\r\033[36m{out_str:<{cols-1}}\033[0m')
            sys.stdout.flush()
            
            i = (i + 1) % len(self._frames)
            await asyncio.sleep(0.1)

    def start(self):
        """Starts the spinner in the background."""
        if not self._running:
            self._running = True
            self.start_time = time.time()
            self._task = asyncio.create_task(self._spin())

    async def stop(self):
        """Stops the spinner and clears the line."""
        if self._running:
            self._running = False
            if self._task:
                await self._task
            sys.stdout.write('\r\033[K') # Clear line
            sys.stdout.flush()

# Global singleton
spinner = TerminalSpinner()
