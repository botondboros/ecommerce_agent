#!/usr/bin/env python3
"""
run.py — Full grocery agent pipeline
──────────────────────────────────────
1. Parse shopping list + user preferences
2. Resolve items with product intelligence (brand quality + substitutes)
3. Bot scrapes all 3 stores (prices + delivery slots)
4. AI scores and picks winner
5. Cart filler logs into winner and adds items
6. Calendar reminder via MCP

Usage:
    python run.py "pasta, milk, eggs, chocolate"
    python run.py --file list.txt --prefs prefs.json
    python run.py "pasta" --stores kifli,auchan --skip-scrape  # reuse bot_results.json
"""

import asyncio, argparse, json, os, sys
from pathlib import Path
from datetime import datetime, timedelta

from product_intelligence import ProductIntelligence
from grocery_bot          import run as run_bot, parse_list
from grocery_agent        import run as run_agent
from cart_filler          import fill_winner_cart, print_summary


# Hungarian search term translations for better store results
HU_SEARCH_TERMS = {
    "pasta":           "tészta",
    "milk":            "tej",
    "eggs":            "tojás",
    "butter":          "vaj",
    "coffee":          "kávé",
    "chocolate":       "csokoládé",
    "salmon":          "lazac",
    "bread":           "kenyér",
    "flour":           "liszt",
    "rice":            "rizs",
    "water":           "ásványvíz",
    "wine":            "bor",
    "beer":            "sör",
    "cheese":          "sajt",
    "yogurt":          "joghurt",
    "chicken":         "csirke",
    "beef":            "marhahús",
    "olive oil":       "olívaolaj",
    "orange juice":    "narancslé",
    "sugar":           "cukor",
    "salt":            "só",
    "pepper":          "bors",
    "onion":           "hagyma",
    "garlic":          "fokhagyma",
    "tomato":          "paradicsom",
    "potato":          "burgonya",
    "apple":           "alma",
    "banana":          "banán",
}

def get_search_term(original_query: str) -> str:
    """Return Hungarian search term if available, else original."""
    q = original_query.lower().strip()
    return HU_SEARCH_TERMS.get(q, original_query)



def load_preferences(path_or_json: str) -> dict:
    """
    Load user preferences from file or inline JSON.
    Format: {"pasta": "Barilla", "milk": "Mizo", "chocolate": "Lindt"}
    """
    if not path_or_json:
        return {}
    if os.path.exists(path_or_json):
        return json.loads(Path(path_or_json).read_text(encoding="utf-8"))
    try:
        return json.loads(path_or_json)
    except json.JSONDecodeError:
        return {}


async def main():
    parser = argparse.ArgumentParser(description="Grocery Agent — full pipeline")
    parser.add_argument("list",       nargs="?", help="Shopping list (comma-separated)")
    parser.add_argument("--file",     help="Shopping list file path")
    parser.add_argument("--prefs",    help='Brand preferences JSON: \'{"pasta":"Barilla"}\'')
    parser.add_argument("--stores",   default="kifli,auchan,tesco")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Reuse existing bot_results.json (skip scraping)")
    parser.add_argument("--skip-cart", action="store_true",
                        help="Skip cart filling (just show recommendation)")
    args = parser.parse_args()

    if args.headless:
        os.environ["HEADLESS"] = "true"

    # ── Parse list ────────────────────────────────────────────────────────────
    if args.file:
        raw_items = parse_list(args.file)
    elif args.list:
        raw_items = parse_list(args.list.replace(",", "\n"))
    else:
        print("Enter shopping list (one item per line, empty line to finish):")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        raw_items = parse_list("\n".join(lines))

    if not raw_items:
        print("No items. Exiting.")
        sys.exit(1)

    # ── Load preferences ──────────────────────────────────────────────────────
    preferences = load_preferences(args.prefs or "")

    # ── Step 1: Product Intelligence ──────────────────────────────────────────
    print("\n" + "="*55)
    print("  Step 1/4: Product Intelligence")
    print("="*55)

    pi = ProductIntelligence()
    resolved = pi.resolve_list(raw_items, preferences=preferences)
    print(pi.format_summary(resolved))

    bot_instructions = pi.to_bot_instructions(resolved)
    Path("bot_instructions.json").write_text(
        json.dumps(bot_instructions, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Items for the bot: use resolved search terms
    # Use Hungarian search terms where available, fall back to original
    bot_items = [get_search_term(r["original_query"]) for r in bot_instructions]
    stores = [s.strip() for s in args.stores.split(",")]

    # ── Step 2: Scrape stores ─────────────────────────────────────────────────
    if not args.skip_scrape:
        print("\n" + "="*55)
        print("  Step 2/4: Scraping stores")
        print("="*55)
        await run_bot(bot_items, stores, "bot_results.json")
    else:
        print("\n  ⏩ Skipping scrape — using existing bot_results.json")

    # ── Step 3: AI Decision ───────────────────────────────────────────────────
    print("\n" + "="*55)
    print("  Step 3/4: AI Scoring & Decision")
    print("="*55)
    decision = run_agent("bot_results.json", "decision.json")

    winner        = decision["winner"]
    winner_reason = decision["winner_reason"]
    winner_slots  = decision.get("winner_slots", [])
    scores        = decision.get("scores", {})

    # Print decision
    print(f"\n  🏆 Winner: {winner.upper()}")
    print(f"  {winner_reason}")
    print(f"\n  Scores:")
    for sid, sc in sorted(scores.items(), key=lambda x: -x[1]["total"]):
        bar = "█" * (sc["total"] // 10) + "░" * (10 - sc["total"] // 10)
        print(f"    {sid:8s} {bar} {sc['total']:3d}  "
              f"(price={sc['price']} delivery={sc['delivery']} quality={sc['quality']})")

    if winner_slots:
        print(f"\n  📦 Available delivery slots ({winner}):")
        for slot in winner_slots[:5]:
            print(f"    • {slot['label']}")

    if decision.get("ai_summary"):
        print(f"\n  💬 {decision['ai_summary']}")

    # ── Step 4: Fill cart ─────────────────────────────────────────────────────
    if not args.skip_cart:
        print("\n" + "="*55)
        print(f"  Step 4/4: Filling cart on {winner.upper()}")
        print("="*55)
        print(f"\n  Opening {winner} in browser and adding {len(bot_instructions)} items...")
        print("  ⚠️  DO NOT click checkout — bot stops at cart page.\n")

        cart_result = await fill_winner_cart(
            winner,
            bot_instructions,
            headless=args.headless,
        )
        print_summary(cart_result)

        # Save cart result
        cart_data = {
            "store":     cart_result.store,
            "added":     cart_result.added,
            "failed":    cart_result.failed,
            "cart_url":  cart_result.cart_url,
            "timestamp": datetime.now().isoformat(),
        }
        Path("cart_result.json").write_text(
            json.dumps(cart_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Calendar reminder tip
        if winner_slots:
            slot = winner_slots[0]
            print(f"\n  📅 Calendar reminder:")
            print(f"     Add to Google Calendar: '{winner.capitalize()} delivery — {slot['label']}'")
            print(f"     Run: python add_calendar.py '{slot['label']}' '{winner}'")
    else:
        print("\n  ⏩ Cart filling skipped.")

    print(f"\n  ✓ Done. Files: bot_results.json · decision.json · cart_result.json")


if __name__ == "__main__":
    asyncio.run(main())
