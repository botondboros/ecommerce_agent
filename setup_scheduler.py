#!/usr/bin/env python3
"""
setup_scheduler.py
──────────────────
Registers a weekly Windows Task Scheduler job that:
  1. Runs grocery_bot.py (scrapes all 3 stores)
  2. Runs grocery_agent.py (AI picks winner)
  3. Runs cart_filler.py (fills winner cart)
  4. Sends a desktop notification when cart is ready

Usage:
    python setup_scheduler.py
    python setup_scheduler.py --day MON --time 09:00
    python setup_scheduler.py --remove   (unregister the task)
"""

import subprocess, sys, os, argparse, json
from pathlib import Path
from datetime import datetime

TASK_NAME  = "GroceryAgent_Weekly"
SCRIPT_DIR = Path(__file__).parent.resolve()
RUNNER     = SCRIPT_DIR / "weekly_run.py"


def create_weekly_runner():
    """
    Creates weekly_run.py — the actual script Task Scheduler calls.
    This is a thin wrapper that calls run.py with the right args
    and handles logging + Windows toast notification.
    """
    content = '''#!/usr/bin/env python3
"""
weekly_run.py
─────────────
Called by Windows Task Scheduler every week.
Runs the full grocery agent pipeline and shows a desktop notification.
"""
import asyncio, sys, os, subprocess, json
from pathlib import Path
from datetime import datetime

# ── Config — edit these ───────────────────────────────────────────────────────
SHOPPING_LIST = """
pasta
milk
eggs
butter
yogurt
salmon
dark chocolate
coffee
olive oil
bread
orange juice
"""

PREFERENCES = {
    # "item keyword": "preferred brand"
    # Leave empty {} to let AI decide everything
    # "pasta":     "Barilla",
    # "chocolate": "Lindt",
}

STORES    = "kifli,auchan,tesco"
LOG_FILE  = Path(__file__).parent / "grocery_weekly.log"
# ─────────────────────────────────────────────────────────────────────────────


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\\n")


def notify(title, message):
    """Windows toast notification."""
    try:
        ps = f\'\'\'
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip(8000, "{title}", "{message}", [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 8
$notify.Dispose()
\'\'\'.format(title=title, message=message)
        subprocess.run(["powershell", "-Command", ps],
                       capture_output=True, timeout=15)
    except Exception:
        pass   # non-critical


async def run():
    log("=" * 55)
    log("  Weekly Grocery Agent — starting")
    log("=" * 55)

    # Write shopping list to temp file
    list_path = Path(__file__).parent / "_weekly_list.txt"
    list_path.write_text(SHOPPING_LIST.strip(), encoding="utf-8")

    # Write preferences
    prefs_path = Path(__file__).parent / "_weekly_prefs.json"
    prefs_path.write_text(json.dumps(PREFERENCES, ensure_ascii=False), encoding="utf-8")

    notify("🛒 Grocery Agent", "Weekly shopping run starting...")

    # Import and run pipeline
    sys.path.insert(0, str(Path(__file__).parent))
    from product_intelligence import ProductIntelligence
    from grocery_bot          import run as run_bot, parse_list
    from grocery_agent        import run as run_agent
    from cart_filler          import fill_winner_cart, print_summary

    items = parse_list(str(list_path))
    log(f"Items: {items}")

    prefs = PREFERENCES
    stores = [s.strip() for s in STORES.split(",")]

    # Step 1: Product intelligence
    log("Step 1: Product intelligence")
    pi = ProductIntelligence()
    resolved = pi.resolve_list(items, preferences=prefs)
    instructions = pi.to_bot_instructions(resolved)
    log(pi.format_summary(resolved))

    bot_items = [r["search_term"] for r in instructions]

    # Step 2: Scrape
    log("Step 2: Scraping stores")
    notify("🛒 Grocery Agent", "Scraping prices from Kifli, Auchan, Tesco...")
    await run_bot(bot_items, stores, "bot_results.json")

    # Step 3: AI decision
    log("Step 3: AI decision")
    decision = run_agent("bot_results.json", "decision.json")
    winner   = decision["winner"]
    log(f"Winner: {winner} — {decision[\'winner_reason\']}")

    # Step 4: Fill cart
    log(f"Step 4: Filling cart on {winner}")
    notify("🛒 Grocery Agent", f"Opening {winner.capitalize()} and filling your cart...")

    cart_result = await fill_winner_cart(winner, instructions, headless=False)

    # Summary
    added  = len(cart_result.added)
    failed = len(cart_result.failed)
    log(f"Cart filled: {added} items added, {failed} failed on {winner}")

    notify(
        "🛒 Cart ready!",
        f"{winner.capitalize()}: {added} items in cart. "
        f"Review and pay at your convenience."
        + (f" ({failed} items not found)" if failed else "")
    )

    log("Weekly run complete.")


if __name__ == "__main__":
    asyncio.run(run())
'''
    RUNNER.write_text(content, encoding="utf-8")
    print(f"✓ Created: {RUNNER}")


def register_task(day: str = "MON", time: str = "09:00"):
    """Register Windows Task Scheduler job."""
    python_exe = sys.executable
    script     = str(RUNNER)

    # schtasks day format: MON TUE WED THU FRI SAT SUN
    day_map = {
        "MON":"MON","TUE":"TUE","WED":"WED","THU":"THU",
        "FRI":"FRI","SAT":"SAT","SUN":"SUN",
        "MONDAY":"MON","TUESDAY":"TUE","WEDNESDAY":"WED",
        "THURSDAY":"THU","FRIDAY":"FRI","SATURDAY":"SAT","SUNDAY":"SUN",
    }
    sched_day = day_map.get(day.upper(), "MON")

    cmd = [
        "schtasks", "/Create", "/F",
        "/TN",  TASK_NAME,
        "/TR",  f'"{python_exe}" "{script}"',
        "/SC",  "WEEKLY",
        "/D",   sched_day,
        "/ST",  time,
        "/RL",  "HIGHEST",
    ]

    print(f"Registering task: every {sched_day} at {time}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✓ Task '{TASK_NAME}' registered successfully.")
        print(f"  Runs: every {sched_day} at {time}")
        print(f"  Script: {script}")
        print(f"  Log: {SCRIPT_DIR / 'grocery_weekly.log'}")
    else:
        print(f"✗ Registration failed: {result.stderr}")
        print("\nTry running as Administrator, or register manually:")
        print(f"  schtasks /Create /TN {TASK_NAME} /TR \"{python_exe} {script}\"")
        print(f"  /SC WEEKLY /D {sched_day} /ST {time} /RL HIGHEST")


def remove_task():
    result = subprocess.run(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✓ Task '{TASK_NAME}' removed.")
    else:
        print(f"Task not found or already removed: {result.stderr}")


def show_config_prompt():
    """Interactive config for weekly_run.py."""
    print("\n── Weekly Grocery Agent Setup ──────────────────────────")
    print("This will register a weekly Windows Task Scheduler job.")
    print()

    day  = input("Day of week [MON/TUE/WED/THU/FRI/SAT/SUN, default MON]: ").strip() or "MON"
    time = input("Time to run [HH:MM, default 09:00]: ").strip() or "09:00"

    print("\nEdit the shopping list in weekly_run.py (SHOPPING_LIST variable)")
    print("Edit brand preferences in weekly_run.py (PREFERENCES variable)")
    print()

    return day, time


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day",    default=None, help="Day: MON/TUE/...")
    parser.add_argument("--time",   default=None, help="Time: HH:MM")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--test",   action="store_true", help="Run immediately once (test)")
    args = parser.parse_args()

    if args.remove:
        remove_task()
        sys.exit(0)

    if args.test:
        create_weekly_runner()
        print("Running weekly_run.py now (test)...")
        subprocess.run([sys.executable, str(RUNNER)])
        sys.exit(0)

    create_weekly_runner()

    if args.day and args.time:
        day, time = args.day, args.time
    else:
        day, time = show_config_prompt()

    register_task(day, time)

    print("\n── Next steps ──────────────────────────────────────────")
    print(f"1. Edit {RUNNER}")
    print("   → Set your SHOPPING_LIST")
    print("   → Set your PREFERENCES (brand preferences)")
    print(f"2. Fill in .env with store credentials")
    print(f"3. Test: python setup_scheduler.py --test")
    print(f"4. View logs: {SCRIPT_DIR / 'grocery_weekly.log'}")
    print(f"5. Remove task: python setup_scheduler.py --remove")
