#!/usr/bin/env python3
"""
grocery_bot.py
──────────────
Playwright-based scraper for Kifli.hu, Auchan Online, Tesco Online.
Searches products, adds to cart, reads delivery slots — never purchases.

Usage:
    pip install playwright python-dotenv
    playwright install chromium
    python grocery_bot.py --list "shopping_list.txt" --output "results.json"

Credentials (set in .env or environment):
    KIFLI_EMAIL, KIFLI_PASSWORD
    AUCHAN_EMAIL, AUCHAN_PASSWORD
    TESCO_EMAIL, TESCO_PASSWORD
"""

import asyncio, json, os, sys, argparse, re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
STORES = {
    "kifli": {
        "url":       "https://www.kifli.hu",
        "email":     os.getenv("KIFLI_EMAIL", ""),
        "password":  os.getenv("KIFLI_PASSWORD", ""),
    },
    "auchan": {
        "url":       "https://www.auchan.hu",
        "email":     os.getenv("AUCHAN_EMAIL", ""),
        "password":  os.getenv("AUCHAN_PASSWORD", ""),
    },
    "tesco": {
        "url":       "https://www.tesco.com/groceries",
        "email":     os.getenv("TESCO_EMAIL", ""),
        "password":  os.getenv("TESCO_PASSWORD", ""),
    },
}

HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO  = int(os.getenv("SLOW_MO", "400"))   # ms — increase if bot detection kicks in


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# KIFLI.HU
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_kifli(page, items: list[str]) -> dict:
    log("── Kifli.hu ─────────────────────────────────────────────")
    result = {"store": "kifli", "products": [], "delivery_slots": [], "cart_total": 0, "error": None}

    try:
        await page.goto("https://www.kifli.hu", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)

        # ── Session check (login handled by bot profile) ───────────────────
        try:
            logged_in = await page.query_selector(
                "[class*='UserName'], a[href*='/profil'], "
                "[data-testid*='user'], [class*='account-name']"
            )
            log("  Kifli: session active" if logged_in else "  Kifli: guest mode (run setup_bot_profile.py)")
        except Exception:
            pass

        # ── Set delivery address (required for product results) ───────────
        try:
            await page.wait_for_timeout(1500)
            # Accept location if modal present
            confirm_btn = await page.query_selector(
                "button:has-text('Ez a tartózkodási helyem'), "
                "button:has-text('Igen'), button:has-text('Rendben')"
            )
            if confirm_btn:
                await confirm_btn.click()
                await page.wait_for_timeout(1000)
                log("  Kifli: location confirmed")
            else:
                # Try to set Budapest address
                addr_btn = await page.query_selector(
                    "button:has-text('Pontos cím'), a:has-text('cím megadása'), "
                    "[class*='address-modal'] button"
                )
                if addr_btn:
                    await addr_btn.click()
                    await page.wait_for_timeout(1000)
                    addr_input = await page.query_selector(
                        "input[placeholder*='cím'], input[placeholder*='Budapest'], "
                        "input[name*='address'], input[type='text']"
                    )
                    if addr_input:
                        await addr_input.fill("Budapest, Váci utca 1, 1052")
                        await page.wait_for_timeout(1200)
                        opt = await page.query_selector("[role='option'], [class*='suggestion'] li")
                        if opt:
                            await opt.click()
                        else:
                            await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1500)
                        log("  Kifli: address set to Budapest")
        except Exception as e:
            log(f"  Kifli: address setup: {e}")

        # ── Search & add each item via URL ───────────────────────────────
        import urllib.parse as _up
        KIFLI_CARD_SEL = (
            "[data-testid='product-card'], article, "
            "[class*='ProductCard'], [class*='product-card'], "
            "li[class*='product'], [class*='ProductTile'], "
            "[class*='product-tile'], [class*='item-card']"
        )
        for item in items:
            # Try raw item name first, then with brand prefix
            raw_item = item.split(" ")[-1] if " " in item else item  # last word = hu term
            search_terms = [item, raw_item] if raw_item != item else [item]
            found_product = False

            for term in search_terms:
                try:
                    log(f"  Kifli: searching '{term}'")
                    for search_url in [
                        f"https://www.kifli.hu/kereses?query={_up.quote(term)}",
                        f"https://www.kifli.hu/search?query={_up.quote(term)}",
                    ]:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(2500)
                        product_card = await page.query_selector(KIFLI_CARD_SEL)
                        if product_card:
                            break

                    if not product_card:
                        continue

                    name_el  = await product_card.query_selector("h2,h3,[class*='title'],[class*='name']")
                    price_el = await product_card.query_selector("[class*='price'],[data-testid*='price']")
                    img_el   = await product_card.query_selector("img")

                    name  = (await name_el.inner_text()).strip()  if name_el  else term
                    price = (await price_el.inner_text()).strip() if price_el else "N/A"
                    img   = await img_el.get_attribute("src")     if img_el   else None

                    add_btn = await product_card.query_selector(
                        "button[data-testid*='add'],button[aria-label*='add'],"
                        "button[class*='AddToCart'],button[class*='add-to-cart'],button:has-text('+')"
                    )
                    if add_btn:
                        await add_btn.click()
                        await page.wait_for_timeout(700)
                        log(f"  Kifli: added '{name[:40]}' @ {price}")
                    result["products"].append({"query": item,"found":True,"name":name,"price":price,"image":img})
                    found_product = True
                    break

                except Exception as e:
                    log(f"  Kifli: error on '{term}': {e}")

            if not found_product:
                log(f"  Kifli: no results for '{item}'")
                result["products"].append({"query": item, "found": False})

        # ── Navigate to checkout to see delivery slots ─────────────────────
        try:
            await page.goto("https://www.kifli.hu/rendeles/kosaram-tartalma", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # Try to get cart total
            total_el = await page.query_selector("[class*='total'], [data-testid*='total']")
            if total_el:
                total_text = await total_el.inner_text()
                nums = re.findall(r"\d[\d\s]*", total_text)
                if nums:
                    result["cart_total"] = int("".join(nums[0].split()))

            # Extract delivery slots
            slot_els = await page.query_selector_all(
                "[class*='DeliverySlot'], [class*='delivery-slot'], [data-testid*='slot'], "
                "[class*='TimeSlot'], button[class*='slot']"
            )
            for slot_el in slot_els[:12]:
                try:
                    slot_text = await slot_el.inner_text()
                    disabled  = await slot_el.get_attribute("disabled")
                    aria_dis  = await slot_el.get_attribute("aria-disabled")
                    available = disabled is None and aria_dis != "true"
                    if slot_text.strip():
                        result["delivery_slots"].append({
                            "label": slot_text.strip().replace("\n", " "),
                            "available": available,
                        })
                except Exception:
                    pass

            log(f"  Kifli: {len(result['delivery_slots'])} delivery slots found")

        except Exception as e:
            log(f"  Kifli: checkout error: {e}")

    except Exception as e:
        result["error"] = str(e)
        log(f"  Kifli: fatal error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# AUCHAN ONLINE
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_auchan(page, items: list[str]) -> dict:
    log("── Auchan Online ─────────────────────────────────────────")
    result = {"store": "auchan", "products": [], "delivery_slots": [], "cart_total": 0, "error": None}

    try:
        await page.goto("https://www.auchan.hu", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Accept cookies
        try:
            await page.click(
                "button#CybotCookiebotDialogBodyButtonAccept, "
                "button[id*='cookie'][id*='Accept'], "
                "button:has-text('Elfogadom'), button:has-text('Elfogad minden')",
                timeout=4000
            )
        except PWTimeout:
            pass

        # ── Login ──────────────────────────────────────────────────────────
        # Login handled by bot profile
        try:
            logged_in = await page.query_selector(
                "[class*='UserName'], [class*='user-name'], "
                "a[href*='profil'], [class*='loggedIn']"
            )
            log("  Auchan: session active" if logged_in else "  Auchan: guest mode")
        except Exception:
            pass

        # ── Search & add each item ─────────────────────────────────────────
        for item in items:
            try:
                log(f"  Auchan: searching '{item}'")

                import urllib.parse as _up_a
                # Use search input box for real results
                search_word = item.lower().split()[-1]
                try:
                    search_box = await page.wait_for_selector(
                        "input[placeholder*='Termékek'], input[placeholder*='keresése'], "
                        "input[placeholder*='információk'], input[type='search']",
                        timeout=4000
                    )
                    await search_box.click()
                    await search_box.fill(item)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(4000)
                except Exception:
                    await page.goto(
                        f"https://www.auchan.hu/search?q={_up_a.quote(item)}",
                        wait_until="domcontentloaded", timeout=15000
                    )
                    await page.wait_for_timeout(4000)

                await page.evaluate("window.scrollTo(0, 400)")
                await page.wait_for_timeout(1000)

                all_cards = await page.query_selector_all("[class*='productCard']")
                card = None
                import re as _re
                for c in all_cards:
                    h = await c.query_selector("h3[title]")
                    if not h: continue
                    n = (await h.get_attribute("title") or "").lower()
                    # Whole-word match: "tojás" must not match "tojásfesték"
                    if _re.search(r'\b' + _re.escape(search_word) + r'\b', n):
                        card = c
                        break

                if not card:
                    log(f"  Auchan: no results for '{item}'")
                    result["products"].append({"query": item, "found": False})
                    continue

                h3_el    = await card.query_selector("h3[title]")
                price_el = await card.query_selector("[class*='WNiPvlkU'], [class*='price']")
                img_el   = await card.query_selector("img")

                name  = await h3_el.get_attribute("title") if h3_el else item
                price = (await price_el.inner_text()).strip() if price_el else "N/A"
                img   = await img_el.get_attribute("src")   if img_el else None

                # Auchan add to cart — confirmed selector from UI
                add_btn = await card.query_selector(
                    "button[aria-label*='Hozzáadás a kosárhoz'], button[aria-label*='hozzáadása a kosárhoz']"
                )
                if add_btn:
                    await add_btn.click()
                    await page.wait_for_timeout(900)
                    log(f"  Auchan: added '{name[:40]}' @ {price}")
                else:
                    log(f"  Auchan: found '{name[:40]}' but no add button")

                result["products"].append({
                    "query": item, "found": True,
                    "name": name, "price": price, "image": img,
                })

            except Exception as e:
                log(f"  Auchan: error on '{item}': {e}")
                result["products"].append({"query": item, "found": False, "error": str(e)})

        # ── Navigate to cart / checkout for delivery slots ─────────────────
        try:
            await page.goto(
                "https://www.auchan.hu/shop/checkout/food",
                wait_until="domcontentloaded", timeout=20000
            )
            await page.wait_for_timeout(2500)

            # Cart total
            total_el = await page.query_selector(
                "[class*='total'], [class*='Total'], [class*='osszeg'], [data-testid*='total']"
            )
            if total_el:
                t = await total_el.inner_text()
                nums = re.findall(r"\d[\d\s]*", t)
                if nums:
                    result["cart_total"] = int("".join(nums[0].split()))

            # Auchan delivery slot selectors
            # Auchan delivery info shown as text block on checkout
            slot_els = await page.query_selector_all(
                "[class*='DeliverySlot'], [class*='delivery-slot'], "
                "[class*='time-slot'], [class*='TimeWindow'], "
                "[class*='szallitas'] [class*='time'], "
                "button[class*='slot'], td[class*='slot']"
            )
            # Also try to read delivery date text directly
            if not slot_els:
                delivery_text_el = await page.query_selector(
                    "[class*='szallitasi-ido'], [class*='delivery-date'], "
                    "[class*='deliveryTime'], p:has-text('között'), "
                    "p:has-text('08:00'), span:has-text('szerda'), "
                    "span:has-text('hétfő'), span:has-text('kedd')"
                )
                if delivery_text_el:
                    txt = await delivery_text_el.inner_text()
                    result["delivery_slots"].append({
                        "label": txt.strip().replace("\n", " "),
                        "available": True,
                    })
                    log(f"  Auchan: delivery slot found: {txt.strip()[:50]}")
            for slot_el in slot_els[:16]:
                try:
                    text     = await slot_el.inner_text()
                    cls      = await slot_el.get_attribute("class") or ""
                    disabled = await slot_el.get_attribute("disabled")
                    available = disabled is None and "unavailable" not in cls.lower() and "foglalt" not in cls.lower()
                    if text.strip():
                        result["delivery_slots"].append({
                            "label":     text.strip().replace("\n", " "),
                            "available": available,
                        })
                except Exception:
                    pass

            log(f"  Auchan: {len(result['delivery_slots'])} delivery slots found")

        except Exception as e:
            log(f"  Auchan: checkout error: {e}")

    except Exception as e:
        result["error"] = str(e)
        log(f"  Auchan: fatal error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# TESCO ONLINE
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_tesco(page, items: list[str]) -> dict:
    log("── Tesco Online ─────────────────────────────────────────")
    result = {"store": "tesco", "products": [], "delivery_slots": [], "cart_total": 0, "error": None}

    try:
        await page.goto("https://bevasarlas.tesco.hu/groceries/hu-HU", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Cookies
        try:
            await page.click("#onetrust-accept-btn-handler, button:has-text('Accept all')", timeout=4000)
        except PWTimeout:
            pass

        # ── Login ──────────────────────────────────────────────────────────
        if STORES["tesco"]["email"]:
            try:
                await page.click("a[href*='sign-in'], a[href*='login'], button:has-text('Sign in')", timeout=5000)
                await page.fill("input[id='email'], input[type='email']", STORES["tesco"]["email"])
                await page.click("button[type='submit'], button:has-text('Continue')")
                await page.wait_for_timeout(2500)
                await page.fill("input[type='password']", STORES["tesco"]["password"])
                await page.click("button[type='submit']")
                await page.wait_for_timeout(3000)
                log("  Tesco: logged in")
            except PWTimeout:
                log("  Tesco: login not found — guest mode")

        # ── Search & add ───────────────────────────────────────────────────
        for item in items:
            try:
                log(f"  Tesco: searching '{item}'")
                await page.goto(
                    f"https://www.tesco.com/groceries/en-GB/search?query={item.replace(' ','+')}&count=5",
                    wait_until="domcontentloaded", timeout=20000
                )
                await page.wait_for_timeout(2500)

                card = await page.query_selector(
                    "[data-auto='product-tile'], article[class*='product'], li[class*='product']"
                )
                if not card:
                    result["products"].append({"query": item, "found": False})
                    continue

                name_el  = await card.query_selector("a[class*='title'], h3, [class*='product-title']")
                price_el = await card.query_selector("[class*='price-per-sellable-unit'], [data-auto*='price']")
                img_el   = await card.query_selector("img")

                name  = await name_el.inner_text()  if name_el  else item
                price = await price_el.inner_text() if price_el else "N/A"
                img   = await img_el.get_attribute("src") if img_el else None

                add_btn = await card.query_selector(
                    "button[data-auto='add-to-cart'], button:has-text('Add'), button[class*='add-button']"
                )
                if add_btn:
                    await add_btn.click()
                    await page.wait_for_timeout(700)

                result["products"].append({
                    "query": item, "found": True,
                    "name": name.strip(), "price": price.strip(), "image": img,
                })
                log(f"  Tesco: added '{name.strip()[:40]}'")

            except Exception as e:
                result["products"].append({"query": item, "found": False, "error": str(e)})

        # ── Delivery slots ─────────────────────────────────────────────────
        try:
            await page.goto(
                "https://bevasarlas.tesco.hu/groceries/hu-HU/slots/delivery",
                wait_until="domcontentloaded", timeout=20000
            )
            await page.wait_for_timeout(2500)

            slot_els = await page.query_selector_all(
                "td[class*='slot'], button[class*='slot'], [data-auto*='slot'], td[class*='available']"
            )
            for slot_el in slot_els[:16]:
                try:
                    text      = await slot_el.inner_text()
                    cls       = await slot_el.get_attribute("class") or ""
                    available = "unavailable" not in cls.lower() and "booked" not in cls.lower()
                    if text.strip():
                        result["delivery_slots"].append({
                            "label": text.strip().replace("\n", " "),
                            "available": available,
                        })
                except Exception:
                    pass

            log(f"  Tesco: {len(result['delivery_slots'])} slots found")

        except Exception as e:
            log(f"  Tesco: checkout error: {e}")

    except Exception as e:
        result["error"] = str(e)
        log(f"  Tesco: fatal error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def run(items: list[str], stores: list[str], output_path: str):
    log(f"Starting grocery bot — {len(items)} items, stores: {stores}")
    results = {}

    async with async_playwright() as pw:

# Bot profile path (created by setup_bot_profile.py)
        BOT_PROFILE = str(Path(__file__).parent / "bot_chrome_profile")

        if Path(BOT_PROFILE).exists():
            log(f"  Using bot profile: {BOT_PROFILE}")
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=BOT_PROFILE,
                    channel="chrome",
                    headless=False,
                    slow_mo=SLOW_MO,
                    args=["--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1440, "height": 900},
                    locale="hu-HU",
                )
                browser = None
            except Exception as e:
                log(f"  Bot profile failed: {e} — fresh browser")
                context = None
        else:
            log("  Bot profile not found — run setup_bot_profile.py first")
            context = None

        if context is None:
            browser = await pw.chromium.launch(
                headless=HEADLESS, slow_mo=SLOW_MO,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="hu-HU",
            )
        else:
            browser = None

        scraper_map = {
            "kifli":  scrape_kifli,
            "auchan": scrape_auchan,
            "tesco":  scrape_tesco,
        }

        for store in stores:
            if store not in scraper_map:
                log(f"Unknown store: {store}")
                continue
            page = await context.new_page()
            try:
                results[store] = await scraper_map[store](page, items)
            except Exception as e:
                results[store] = {"store": store, "error": str(e), "products": [], "delivery_slots": []}
            finally:
                await page.close()

        if browser:
            await browser.close()
        else:
            await context.close()

    # Write output
    output = {
        "timestamp": datetime.now().isoformat(),
        "items_requested": items,
        "stores": results,
    }
    Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Results written to {output_path}")
    return output


def parse_list(path_or_text: str) -> list[str]:
    """Accept file path or raw newline-separated text."""
    if os.path.exists(path_or_text):
        text = Path(path_or_text).read_text(encoding="utf-8")
    else:
        text = path_or_text
    items = []
    for line in text.splitlines():
        line = re.sub(r"^[-•*\d.]+\s*", "", line).strip()
        if line:
            items.append(line)
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grocery Bot — scrapes carts & delivery slots")
    parser.add_argument("--list",   required=True,  help="Shopping list file path or text")
    parser.add_argument("--stores", default="kifli,auchan,tesco", help="Comma-separated stores")
    parser.add_argument("--output", default="bot_results.json", help="Output JSON path")
    args = parser.parse_args()

    items  = parse_list(args.list)
    stores = [s.strip() for s in args.stores.split(",")]

    if not items:
        print("No items found in list. Exiting.")
        sys.exit(1)

    asyncio.run(run(items, stores, args.output))
