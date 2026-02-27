from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.align import Align
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
import time
import psutil
from datetime import datetime
import itertools
import random

console = Console()

# ============================================================
# BOOT SEQUENCE
# ============================================================
def boot_sequence():
    console.clear()
    console.print("\n[bold cyan]GALACTIC AI — SOVEREIGN ORBITAL INITIALIZATION[/bold cyan]\n")

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        phases = [
            "Powering Quantum Core",
            "Syncing Memory Matrix",
            "Linking Model Grid",
            "Registering Skill Arsenal",
            "Stabilizing Pulse Engine",
        ]
        for phase in phases:
            task = progress.add_task(phase, total=None)
            time.sleep(0.9)
            progress.remove_task(task)

    console.print("[bold green]ALL SYSTEMS ONLINE[/bold green]")
    time.sleep(1.2)
    console.clear()


# ============================================================
# HEADER PANEL
# ============================================================
def build_header(pulse_state):
    title = Text("GALACTIC AI\n", style="bold")
    title.stylize("gradient(#4B0082,#00FFFF)")

    pulse_style = "bold green" if pulse_state else "bold bright_black"
    pulse = Text("[ PULSE ENGINE: ACTIVE ]", style=pulse_style)

    status = Text("STATUS: ALL SYSTEMS NOMINAL", style="bold bright_cyan")

    block = Text()
    block.append(title)
    block.append("\n")
    block.append(pulse + "\n\n")
    block.append(status)

    return Panel(
        Align.center(block),
        border_style="bright_blue",
        box=box.DOUBLE,
        padding=(1, 4),
    )


# ============================================================
# METRICS PANEL
# ============================================================
def build_metrics():
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    now = datetime.now().strftime("%H:%M:%S")

    def colorize(value):
        if value < 70:
            return "green"
        elif value < 90:
            return "yellow"
        return "red"

    table = Table.grid(padding=1)
    table.add_row("CPU:", f"[{colorize(cpu)}]{cpu}%[/]")
    table.add_row("RAM:", f"[{colorize(ram)}]{ram}%[/]")
    table.add_row("DISK:", f"[{colorize(disk)}]{disk}%[/]")
    table.add_row("TIME:", f"[cyan]{now}[/]")

    return Panel(
        table,
        title="SYSTEM TELEMETRY",
        border_style="bright_blue",
        box=box.ROUNDED,
    )


# ============================================================
# LOG ENGINE
# ============================================================
log_buffer = []

SOURCES = ["Core", "Model", "Skills", "Memory", "Async"]
MESSAGES = [
    "Async loop stabilized.",
    "Tool registry synchronized.",
    "Model heartbeat nominal.",
    "Memory index optimized.",
    "Skill layer verified.",
    "Inference pipeline ready.",
]


def add_log():
    timestamp = datetime.now().strftime("%H:%M:%S")
    source = random.choice(SOURCES)
    message = random.choice(MESSAGES)

    entry = Text()
    entry.append(f"[{timestamp}] ", style="dim")
    entry.append(f"[{source}] ", style="bold cyan")
    entry.append(message, style="white")

    log_buffer.append(entry)



def build_logs():
    table = Table.grid()
    table.expand = True

    for entry in log_buffer[-20:]:
        table.add_row(entry)

    return Panel(
        table,
        title="SYSTEM STREAM",
        border_style="bright_blue",
        box=box.ROUNDED,
    )


# ============================================================
# LAYOUT
# ============================================================
def build_layout():
    layout = Layout()

    layout.split(
        Layout(name="upper", size=12),
        Layout(name="lower"),
    )

    layout["upper"].split_row(
        Layout(name="header"),
        Layout(name="metrics", size=32),
    )

    return layout


# ============================================================
# MAIN DASHBOARD LOOP
# ============================================================
def run():
    boot_sequence()

    layout = build_layout()
    pulse_cycle = itertools.cycle([True, False])

    with Live(layout, refresh_per_second=4, screen=True):
        while True:
            pulse_state = next(pulse_cycle)

            add_log()

            if psutil.cpu_percent() > 85:
                warning = Text()
                warning.append(f"[{datetime.now().strftime('%H:%M:%S')}] ", style="dim")
                warning.append("[Core] ", style="bold cyan")
                warning.append("High CPU load detected.", style="yellow")
                log_buffer.append(warning)

            layout["header"].update(build_header(pulse_state))
            layout["metrics"].update(build_metrics())
            layout["lower"].update(build_logs())

            time.sleep(0.8)


# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        console.clear()
        console.print("\n[bold cyan]GALACTIC AI — SHUTDOWN COMPLETE[/bold cyan]\n")
