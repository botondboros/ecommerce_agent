#!/usr/bin/env python3
"""
setup_bot_profile.py
─────────────────────
One-time setup: creates a dedicated Chrome profile for the bot
and lets you log in manually to all 3 stores.
After this, the bot reuses the saved session — no login needed.

Usage (run ONCE):
    python setup_bot_profile.py
"""
import asyncio, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

# Bot profile stored next to the script — separate from your main Chrome
BOT_PROFILE = str(Path(__file__).parent / "bot_chrome_profile")

async def main():
    print("="*55)
    print("  Grocery Bot — One-time Profile Setup")
    print("="*55)
    print(f"\nBot profile directory: {BOT_PROFILE}")
    print("\nThis will open Chrome. Please log in to:")
    print("  1. Kifli.hu")
    print("  2. Auchan Online")
    print("  3. Tesco Online")
    print("\nWhen done, close the browser window.")
    print("The bot will reuse this session every week.\n")
    input("Press ENTER to open Chrome...")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=BOT_PROFILE,
            channel="chrome",
            headless=False,
            slow_mo=0,
            viewport={"width": 1440, "height": 900},
            locale="hu-HU",
        )
        page = await context.new_page()

        # Open all 3 stores in tabs
        await page.goto("https://www.kifli.hu", wait_until="domcontentloaded")

        p2 = await context.new_page()
        await p2.goto("https://www.auchan.hu", wait_until="domcontentloaded")

        p3 = await context.new_page()
        await p3.goto("https://www.tesco.hu/account/login/hu-HU?from=https%3A%2F%2Fbevasarlas.tesco.hu%2Fgroceries%2Fhu-HU", wait_until="domcontentloaded")

        print("\nChrome is open with 3 tabs.")
        print("Log in to each site, then come back here and press ENTER.")
        input("\nPress ENTER when you have logged in to all sites...")

        await context.close()

    print(f"\n✓ Profile saved to: {BOT_PROFILE}")
    print("The bot will now use this profile automatically.")
    print("\nNext step: run the grocery agent:")
    print('  python run.py "pasta, tej, tojás, vaj..."')

if __name__ == "__main__":
    asyncio.run(main())
