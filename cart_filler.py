#!/usr/bin/env python3
"""
cart_filler.py
──────────────
After grocery_agent.py picks a winner, this module logs into that
store and adds the recommended products to the cart.
Does NOT proceed to checkout or payment.

Usage:
    python cart_filler.py --store auchan --instructions bot_instructions.json
    python cart_filler.py --store kifli   --instructions bot_instructions.json
"""

import asyncio, json, os, sys, argparse, re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class CartResult:
    store:      str
    added:      list[dict]
    failed:     list[dict]
    cart_url:   str = ""
    screenshot: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def safe_click(page, selectors: list[str], timeout=5000) -> bool:
    """Try multiple selectors, return True if one worked."""
    for sel in selectors:
        try:
            await page.click(sel, timeout=timeout)
            return True
        except PWTimeout:
            continue
    return False


async def safe_fill(page, selectors: list[str], value: str, timeout=5000) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout)
            await el.click()
            await el.fill("")
            await el.type(value, delay=55)
            return True
        except PWTimeout:
            continue
    return False


async def dismiss_popups(page):
    """Dismiss cookie banners and modals."""
    popup_selectors = [
        "#CybotCookiebotDialogBodyButtonAccept",
        "[id*='cookie'] button:has-text('Elfogad')",
        "[id*='cookie'] button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('Agree')",
        "[class*='modal'] button:has-text('Bezárás')",
        "[class*='modal'] button:has-text('Close')",
        "[aria-label='Close']",
    ]
    for sel in popup_selectors:
        try:
            await page.click(sel, timeout=2000)
            await page.wait_for_timeout(500)
        except PWTimeout:
            pass


async def search_and_add(page, search_term: str, search_selectors: list[str],
                          result_selectors: list[str], add_selectors: list[str],
                          fallback_terms: list[str] = None) -> dict:
    """
    Generic search-and-add: searches for a term, clicks first result's add button.
    Falls back to fallback_terms if first search yields no results.
    """
    terms_to_try = [search_term] + (fallback_terms or [])

    for term in terms_to_try:
        log(f"  Searching: '{term}'")
        try:
            # Type into search
            found_search = await safe_fill(page, search_selectors, term, timeout=6000)
            if not found_search:
                continue
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2200)

            # Find first product card
            card = None
            for sel in result_selectors:
                card = await page.query_selector(sel)
                if card:
                    break

            if not card:
                log(f"  No results for '{term}'")
                continue

            # Extract name + price
            name_el  = await card.query_selector("h2,h3,[class*='title'],[class*='name']")
            price_el = await card.query_selector("[class*='price'],[data-testid*='price']")
            name  = (await name_el.inner_text()).strip()  if name_el  else term
            price = (await price_el.inner_text()).strip() if price_el else "N/A"

            # Click add-to-cart
            add_btn = None
            for sel in add_selectors:
                add_btn = await card.query_selector(sel)
                if add_btn:
                    break

            if add_btn:
                await add_btn.click()
                await page.wait_for_timeout(900)
                log(f"  ✓ Added: {name[:50]} @ {price}")
                return {"query": search_term, "found": name, "price": price, "success": True}
            else:
                log(f"  ⚠ Found '{name}' but no add-to-cart button")
                continue

        except Exception as e:
            log(f"  Error on '{term}': {e}")
            continue

    return {"query": search_term, "found": None, "success": False}


# ══════════════════════════════════════════════════════════════════════════════
# KIFLI.HU
# ══════════════════════════════════════════════════════════════════════════════

async def fill_cart_kifli(page, instructions: list[dict]) -> CartResult:
    log("── Filling cart: Kifli.hu ───────────────────────────────")
    result = CartResult(store="kifli", added=[], failed=[])

    # Navigate + dismiss popups
    await page.goto("https://www.kifli.hu", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1500)
    await dismiss_popups(page)

    # Session handled by bot_chrome_profile — no login needed
    log("  Kifli: using saved session from bot profile")

    # Clear existing cart before adding new items
    try:
        await page.goto("https://www.kifli.hu/rendeles/kosaram-tartalma",
                        wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        clear_btn = await page.query_selector(
            "button:has-text('törlése'), a:has-text('törlése'), "
            "[data-testid*='clear-cart'], [data-testid*='empty-cart']"
        )
        if clear_btn:
            await clear_btn.click()
            await page.wait_for_timeout(1000)
            confirm = await page.query_selector("button:has-text('Igen'), button:has-text('Törlés')")
            if confirm:
                await confirm.click()
                await page.wait_for_timeout(1000)
            log("  Kifli: cart cleared")
    except Exception as e:
        log(f"  Kifli: cart clear skipped: {e}")

    # Add each item via URL search
    import urllib.parse as _up
    # Selectors confirmed from Kifli.hu UI
    CARD_SEL = (
        "article[data-testid='product-card'], "
        "[class*='ProductCard'], [class*='product-card'], "
        "li[class*='product'], [class*='ProductTile'], "
        "[data-testid='product-tile']"
    )
    # Green + circle button on Kifli product cards
    ADD_SEL = (
        "button[data-testid='add-to-cart'], "
        "button[data-testid*='add'], "
        "button[aria-label*='Hozzáad'], button[aria-label*='kosár'], "
        "button[class*='AddToCart'], button[class*='add-to-cart'], "
        "[class*='addButton'], [class*='AddButton'], "
        "button:has-text('+')"
    )
    for instr in instructions:
        # Try: original query, then brand+query, then just last word
        oq = instr["original_query"]
        st = instr["search_term"]
        terms = list(dict.fromkeys([oq, st] + instr.get("fallback_terms", [])))
        added = False
        for term in terms:
            try:
                short = term.split()[-1] if len(term.split()) > 2 else term
                for url in [
                    f"https://www.kifli.hu/kereses?query={_up.quote(short)}",
                    f"https://www.kifli.hu/kereses?query={_up.quote(term)}",
                ]:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1200)
                    card = await page.query_selector(CARD_SEL)
                    if card: break
                if not card: continue
                name_el  = await card.query_selector("h2,h3,[class*='title'],[class*='name']")
                price_el = await card.query_selector("[class*='price'],[data-testid*='price']")
                img_el   = await card.query_selector("img")
                name  = (await name_el.inner_text()).strip() if name_el  else term
                price = (await price_el.inner_text()).strip() if price_el else "N/A"
                img   = await img_el.get_attribute("src")    if img_el   else None
                add_btn = await card.query_selector(ADD_SEL)
                if add_btn:
                    await add_btn.click()
                    await page.wait_for_timeout(700)
                    log(f"  ✓ Added: {name[:50]} @ {price}")
                    result.added.append({"query":oq,"found":name,"price":price,"success":True})
                    added = True
                    break
            except Exception as e:
                log(f"  Kifli cart error on '{term}': {e}")
        if not added:
            result.failed.append({"query": oq, "success": False})

    # Navigate to cart page
    try:
        await page.goto("https://www.kifli.hu/rendeles/kosaram-tartalma", wait_until="domcontentloaded", timeout=15000)
        result.cart_url = page.url
        # Screenshot
        ss_path = "kifli_cart.png"
        await page.screenshot(path=ss_path, full_page=False)
        result.screenshot = ss_path
        log(f"  Kifli cart: {len(result.added)} items added, screenshot: {ss_path}")
    except Exception as e:
        log(f"  Kifli cart page error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# AUCHAN ONLINE
# ══════════════════════════════════════════════════════════════════════════════

async def fill_cart_auchan(page, instructions: list[dict]) -> CartResult:
    log("── Filling cart: Auchan Online ──────────────────────────")
    result = CartResult(store="auchan", added=[], failed=[])

    await page.goto("https://www.auchan.hu", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)
    await dismiss_popups(page)

    # Session handled by bot_chrome_profile
    log("  Auchan: using saved session from bot profile")

    import urllib.parse as _up_a
    for instr in instructions:
        terms = list(dict.fromkeys(
            [instr["original_query"]]
            + instr.get("fallback_terms", [])
            + [instr["search_term"]]
        ))
        added = False
        for term in terms:
            try:
                # Use shortest meaningful word for better results
                words = [w for w in term.split() if len(w) > 3]
                short = words[-1] if words else term
                log(f"  Auchan: searching '{short}'")
                # Use search input box — URL search returns promo items
                await page.goto("https://www.auchan.hu", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                try:
                    search_box = await page.wait_for_selector(
                        "input[placeholder*='Termékek'], input[placeholder*='keresése'], "
                        "input[placeholder*='információk'], input[type='search']",
                        timeout=5000
                    )
                    await search_box.click()
                    await search_box.fill(short)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(4000)
                except Exception:
                    # Fallback to URL
                    await page.goto(
                        f"https://www.auchan.hu/search?q={_up_a.quote(short)}",
                        wait_until="domcontentloaded", timeout=15000
                    )
                    await page.wait_for_timeout(4000)

                # Scroll to load results
                await page.evaluate("window.scrollTo(0, 400)")
                await page.wait_for_timeout(1500)

                # Find card where name matches search term
                cards = await page.query_selector_all("[class*='productCard']")
                if not cards:
                    continue

                card = None
                import re as _re2
                for c in cards:
                    h = await c.query_selector("h3[title]")
                    if not h: continue
                    n = (await h.get_attribute("title") or "").lower()
                    if _re2.search(r'\b' + _re2.escape(short.lower()) + r'\b', n):
                        card = c
                        break
                # If no match found, skip entirely (don't add wrong items)
                if not card:
                    log(f"  Auchan: no relevant result for '{short}'")
                    continue

                h3_el    = await card.query_selector("h3[title]")
                price_el = await card.query_selector("[class*='WNiPvlkU']")
                name  = await h3_el.get_attribute("title") if h3_el else term
                price = (await price_el.inner_text()).strip() if price_el else "N/A"

                # Confirmed add button selector from debug
                add_btn = await card.query_selector(
                    "button[aria-label*='Hozzáadás a kosárhoz'], button[aria-label*='hozzáadása a kosárhoz']"
                )
                if add_btn:
                    await add_btn.click()
                    await page.wait_for_timeout(800)
                    log(f"  ✓ Added: {name[:50]} @ {price}")
                    result.added.append({"query": instr["original_query"], "found": name, "price": price, "success": True})
                    added = True
                    break
                else:
                    # Already in cart? Try increment button
                    incr = await card.query_selector("button[aria-label*='hozzáadása a kosárhoz']")
                    if incr:
                        await incr.click()
                        await page.wait_for_timeout(800)
                        log(f"  ✓ Added (incr): {name[:50]}")
                        result.added.append({"query": instr["original_query"], "found": name, "price": price, "success": True})
                        added = True
                        break
                    log(f"  Auchan: found '{name[:40]}' but no add button")
            except Exception as e:
                log(f"  Auchan: error on '{term}': {e}")
        if not added:
            result.failed.append({"query": instr["original_query"], "success": False})
    # Navigate to cart
    try:
        await page.goto("https://www.auchan.hu/shop/checkout/food",
                        wait_until="domcontentloaded", timeout=15000)
        result.cart_url = page.url
        ss_path = "auchan_cart.png"
        await page.screenshot(path=ss_path, full_page=False)
        result.screenshot = ss_path
        log(f"  Auchan cart: {len(result.added)} items added, screenshot: {ss_path}")
    except Exception as e:
        log(f"  Auchan cart page error: {e}")

    return result

# ══════════════════════════════════════════════════════════════════════════════
# TESCO ONLINE
# ══════════════════════════════════════════════════════════════════════════════

async def fill_cart_tesco(page, instructions: list[dict]) -> CartResult:
    log("── Filling cart: Tesco Online ───────────────────────────")
    result = CartResult(store="tesco", added=[], failed=[])

    await page.goto("https://bevasarlas.tesco.hu/groceries/hu-HU", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1500)
    await dismiss_popups(page)

    # Login
    email    = os.getenv("TESCO_EMAIL", "")
    password = os.getenv("TESCO_PASSWORD", "")
    if email:
        try:
            await safe_click(page, [
                "a[href*='sign-in']", "a[href*='login']",
                "button:has-text('Sign in')", "[data-auto='sign-in-link']",
            ])
            await page.wait_for_timeout(1500)
            await safe_fill(page, ["input[id='email']","input[type='email']"], email)
            await safe_click(page, ["button[type='submit']","button:has-text('Continue')"])
            await page.wait_for_timeout(1200)
            await safe_fill(page, ["input[type='password']","input[id='password']"], password)
            await safe_click(page, ["button[type='submit']","button:has-text('Sign in')"])
            await page.wait_for_timeout(3000)
            await dismiss_popups(page)
            log("  Tesco: logged in")
        except Exception as e:
            log(f"  Tesco: login error: {e}")

    for instr in instructions:
        # Tesco: use URL search instead of typing
        term = instr["search_term"]
        fallbacks = instr.get("fallback_terms", []) + [instr["original_query"]]
        terms_to_try = [term] + fallbacks
        added = False

        for t in terms_to_try:
            try:
                await page.goto(
                    f"https://bevasarlas.tesco.hu/groceries/hu-HU/search?query={t.replace(' ','+')}",
                    wait_until="domcontentloaded", timeout=20000
                )
                await page.wait_for_timeout(1800)

                card = await page.query_selector(
                    "[data-auto='product-tile'], article[class*='product'], li[class*='product']"
                )
                if not card:
                    continue

                name_el  = await card.query_selector("a[class*='title'],h3,[class*='product-title']")
                price_el = await card.query_selector("[class*='price-per-sellable'],[data-auto*='price']")
                name  = (await name_el.inner_text()).strip()  if name_el  else t
                price = (await price_el.inner_text()).strip() if price_el else "N/A"

                add_btn = await card.query_selector(
                    "button[data-auto='add-to-cart'],button:has-text('Add'),button[class*='add-button']"
                )
                if add_btn:
                    await add_btn.click()
                    await page.wait_for_timeout(900)
                    log(f"  ✓ Tesco added: {name[:50]} @ {price}")
                    result.added.append({"query": instr["original_query"], "found": name,
                                          "price": price, "success": True})
                    added = True
                    break
            except Exception as e:
                log(f"  Tesco error '{t}': {e}")
                continue

        if not added:
            result.failed.append({"query": instr["original_query"], "success": False})

    # Cart page
    try:
        await page.goto("https://bevasarlas.tesco.hu/groceries/hu-HU/trolley",
                        wait_until="domcontentloaded", timeout=15000)
        result.cart_url = page.url
        ss_path = "tesco_cart.png"
        await page.screenshot(path=ss_path)
        result.screenshot = ss_path
        log(f"  Tesco cart: {len(result.added)} items, screenshot: {ss_path}")
    except Exception as e:
        log(f"  Tesco cart error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

FILLERS = {
    "kifli":  fill_cart_kifli,
    "auchan": fill_cart_auchan,
    "tesco":  fill_cart_tesco,
}


async def fill_winner_cart(store: str, instructions: list[dict],
                            headless: bool = False) -> CartResult:
    """
    Main entry point: open browser, log in to winner store, fill cart.
    Called by run.py after decision.json is ready.
    """
    if store not in FILLERS:
        raise ValueError(f"Unknown store: {store}. Choose from: {list(FILLERS)}")

    async with async_playwright() as pw:


        BOT_PROFILE = str(Path(__file__).parent / "bot_chrome_profile")
        if Path(BOT_PROFILE).exists():
            log(f"  Using bot profile: {BOT_PROFILE}")
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=BOT_PROFILE,
                    channel="chrome",
                    headless=False,
                    slow_mo=int(os.getenv("SLOW_MO", "450")),
                    args=["--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1440, "height": 900},
                    locale="hu-HU",
                )
                browser = None
            except Exception as e:
                log(f"  Bot profile failed: {e} — fresh browser")
                context = None
        else:
            log("  ⚠ Bot profile not found — run setup_bot_profile.py first!")
            context = None

        if context is None:
            browser = await pw.chromium.launch(
                headless=headless,
                slow_mo=int(os.getenv("SLOW_MO", "450")),
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="hu-HU",
            )
        else:
            browser = None

        page = await context.new_page()


        try:
            cart_result = await FILLERS[store](page, instructions)
        finally:
            # Keep browser open briefly so user can see the cart
            log(f"\n  🛒 Cart is ready in the browser window.")
            log(f"  ⏸  Browser stays open for 30 seconds — review your cart.")
            log(f"  ❌ DO NOT click checkout — close the browser when done.")
            try:
                await page.wait_for_timeout(30_000)
            except Exception:
                pass  # User closed browser early — that's fine
            if browser:
                await browser.close()
            else:
                await context.close()

    return cart_result


def print_summary(result: CartResult):
    print(f"\n{'='*55}")
    print(f"  🛒 Cart filled: {result.store.upper()}")
    print(f"  ✓ Added:  {len(result.added)} items")
    if result.failed:
        print(f"  ✗ Failed: {len(result.failed)} items")
        for f in result.failed:
            print(f"    - {f['query']}")
    if result.screenshot:
        print(f"  📸 Screenshot: {result.screenshot}")
    if result.cart_url:
        print(f"  🔗 Cart URL:   {result.cart_url}")
    print(f"{'='*55}\n")
    print("  ⚠️  Review your cart and complete checkout manually.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fill winner store cart")
    parser.add_argument("--store",        required=True, help="Store: kifli | auchan | tesco")
    parser.add_argument("--instructions", required=True, help="Path to bot_instructions.json")
    parser.add_argument("--headless",     action="store_true")
    args = parser.parse_args()

    instructions = json.loads(Path(args.instructions).read_text())
    result = asyncio.run(fill_winner_cart(args.store, instructions, args.headless))
    print_summary(result)
