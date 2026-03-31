#!/usr/bin/env python3
"""
grocery_agent.py
────────────────
Reads bot_results.json, applies AI brand-quality intelligence,
scores each store, picks winner, outputs decision.json.

Usage:
    python grocery_agent.py --input bot_results.json --output decision.json
"""

import json, argparse, os, sys, re
from datetime import datetime
from pathlib import Path
import anthropic

# ── Brand quality database ─────────────────────────────────────────────────────
# Format: keyword → {brand: score 1-5, ...}
# Score: 5=exceptional, 4=very good, 3=good, 2=acceptable, 1=budget
BRAND_QUALITY = {
    "pasta|tészta|spaghetti|penne|fusilli|tagliatelle": {
        "De Cecco":   5, "Rummo":     5, "Garofalo":  5,
        "Barilla":    4, "La Molisana":4,
        "Pasta Reggia":3, "Gyermelyi": 2, "Tesco":     2,
        "Everyday":   1, "Auchan":    1,
    },
    "olive oil|olívaolaj": {
        "Frantoia":   5, "Podere":    5, "Laudemio":  5,
        "Filippo Berio":4, "Bertolli": 3,
        "Monini":     4, "Gallo":     3,
        "Tesco":      2, "Everyday":  1,
    },
    "cheese|sajt|mozzarella|parmesan|parmezán": {
        "Grana Padano":5, "Parmigiano Reggiano":5, "Burrata":5,
        "Fior di Latte":4, "Presidente":4,
        "Tesco Finest":4, "Philadelphia":3,
        "Tesco":      2, "Everyday":  1,
    },
    "coffee|kávé|espresso": {
        "Lavazza Super Crema":5, "Illy":5, "Peet's":5,
        "Lavazza":    4, "Nespresso": 4, "Kimbo": 4,
        "Tchibo":     3, "Douwe Egberts":3,
        "Tesco":      2, "Everyday":  1,
    },
    "milk|tej|tejet": {
        "Organic bio":4, "Parmalat":  3, "Nönnenmacher":4,
        "Mizo":       3, "Sole Mizo": 3,
        "Tesco":      2, "Everyday":  1,
    },
    "bread|kenyér": {
        "Sourdough|kovászos":4, "Artisan":  4,
        "Mestemacher": 4, "Lieken":   3,
        "Tesco Finest":3, "Tesco":    2, "Everyday":1,
    },
    "chocolate|csokoládé": {
        "Valrhona":   5, "Amedei":    5, "Michel Cluizel":5,
        "Lindt Excellence":4, "Lindt": 4, "Green & Black's":4,
        "Milka":      3, "Nestlé":    2,
        "Tesco":      2, "Everyday":  1,
    },
    "salmon|lazac": {
        "Faroe Island":5, "Wild Alaska":5, "Scottish":4,
        "Atlantic":   3,
        "Tesco":      2, "Everyday":  1,
    },
    "butter|vaj": {
        "Kerrygold":  5, "Président": 4, "Elle & Vire":4,
        "Anchor":     4, "Lurpak":    4,
        "Mizo":       3, "Tesco":     2, "Everyday":1,
    },
    "yogurt|joghurt": {
        "Skyr":       5, "Fage":      5, "Chobani":   4,
        "Activia bio":4, "Activia":   3, "Müller":    3,
        "Tesco":      2, "Everyday":  1,
    },
}

STORE_PREMIUM_BONUS = {
    "auchan": 1.05,
    "kifli":  1.15,
    "tesco":  0.90,
}

STORE_DELIVERY_SCORE = {
    "auchan": 65,
    "kifli":  75,
    "tesco":  55,
}

STORE_PRICE_BASE = {
    "kifli":  55,
    "auchan": 72,
    "tesco":  78,
}

STORE_CATEGORY_COVERAGE = {
    "kifli":  80,
    "auchan": 85,
    "tesco":  75,
}

PRICE_QUALITY_THRESHOLD = 0.05


def match_brand_quality(product_name: str) -> tuple[str | None, int]:
    """
    Returns (brand_name, quality_score) for a product name.
    quality_score: 1-5, None if no brand detected.
    """
    name_lower = product_name.lower()
    for category_pattern, brands in BRAND_QUALITY.items():
        # Check if this category applies
        if not any(re.search(kw, name_lower) for kw in category_pattern.split("|")):
            continue
        # Find matching brand
        for brand, score in brands.items():
            if brand.lower() in name_lower:
                return brand, score
    return None, 3   # default mid-quality


def score_store(store_result: dict, all_totals: dict) -> dict:
    """
    Score a store on 5 dimensions:
      price      — based on scraped cart total (real) or market knowledge (estimated)
      delivery   — slot speed + availability
      quality    — product quality from brand DB + store premium range
      coverage   — how well the store covers the shopping list
      found_rate — % of items actually found in scrape
    """
    if store_result.get("error"):
        return {"total": 0, "price": 0, "delivery": 0, "quality": 0, "slots_available": 0}

    store_id   = store_result["store"]
    products   = store_result.get("products", [])
    slots      = store_result.get("delivery_slots", [])
    cart_total = store_result.get("cart_total", 0)

    # ── Price score ──────────────────────────────────────────────────────────
    real_totals = {k: v for k, v in all_totals.items() if v > 0}
    if cart_total and real_totals and len(real_totals) >= 2:
        # Real prices available — compare directly
        min_t = min(real_totals.values())
        max_t = max(real_totals.values())
        if max_t > min_t:
            price_score = 100 - int(100 * (cart_total - min_t) / (max_t - min_t))
        else:
            price_score = 80
    else:
        # No real prices — use market knowledge base scores
        price_score = STORE_PRICE_BASE.get(store_id, 65)

    # ── Delivery score ───────────────────────────────────────────────────────
    available_slots = [s for s in slots if s.get("available")]
    slot_bonus      = min(len(available_slots) * 4, 15)
    delivery_score  = min(100, STORE_DELIVERY_SCORE.get(store_id, 60) + slot_bonus)

    # ── Quality score ────────────────────────────────────────────────────────
    found_products = [p for p in products if p.get("found") and p.get("name")]
    if found_products:
        q_scores = []
        for p in found_products:
            _, q = match_brand_quality(p.get("name", p.get("query", "")))
            q_scores.append(q)
        base_quality = sum(q_scores) / len(q_scores) * 20
    else:
        base_quality = 60   # fallback
    quality_score = int(min(100, base_quality * STORE_PREMIUM_BONUS.get(store_id, 1.0)))

    # ── Coverage score (% of items found) ────────────────────────────────────
    if products:
        found_rate   = len(found_products) / len(products)
        coverage_score = int(STORE_CATEGORY_COVERAGE.get(store_id, 75) * (0.5 + 0.5 * found_rate))
    else:
        coverage_score = STORE_CATEGORY_COVERAGE.get(store_id, 75)

    # ── Weighted total ────────────────────────────────────────────────────────
    # Price 35%, Delivery 30%, Quality 20%, Coverage 15%
    total = int(
        0.35 * price_score +
        0.30 * delivery_score +
        0.20 * quality_score +
        0.15 * coverage_score
    )

    return {
        "price":           price_score,
        "delivery":        delivery_score,
        "quality":         quality_score,
        "coverage":        coverage_score,
        "total":           total,
        "slots_available": len(available_slots),
        "cart_total":      cart_total,
        "found_count":     len(found_products),
    }


def pick_winner(scores: dict, totals: dict) -> tuple[str, str]:
    """
    Pick winner by total score, but apply 5% price-quality rule:
    If a cheaper store's total is <5% of cheapest price but quality is 1 point
    higher → prefer the quality option.
    """
    sorted_stores = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)
    winner_id, winner_score = sorted_stores[0]

    # Check if runner-up offers better quality within 5% price difference
    if len(sorted_stores) > 1:
        runner_id, runner_score = sorted_stores[1]
        w_price = totals.get(winner_id, 0)
        r_price = totals.get(runner_id, 0)
        if w_price > 0 and r_price > 0:
            price_diff_pct = (r_price - w_price) / w_price if r_price > w_price else 0
            quality_diff   = runner_score["quality"] - winner_score["quality"]
            if quality_diff > 10 and price_diff_pct <= PRICE_QUALITY_THRESHOLD:
                winner_id, winner_score = runner_id, runner_score
                return winner_id, (
                    f"Although {runner_id.capitalize()} is {price_diff_pct*100:.1f}% more expensive, "
                    f"it offers significantly better product quality (+{quality_diff} quality points) "
                    f"within the 5% price tolerance rule."
                )

    reasons = []
    if winner_score["delivery"] >= 85:
        reasons.append("fastest delivery")
    if winner_score["price"] >= 80:
        reasons.append("most competitive pricing")
    if winner_score["quality"] >= 75:
        reasons.append("best product quality range")
    slots = winner_score.get("slots_available", 0)
    if slots >= 4:
        reasons.append(f"{slots} delivery slots available today")

    reason = (
        f"{winner_id.capitalize()} scores highest overall. "
        + (f"Strengths: {', '.join(reasons)}." if reasons else "")
    )
    return winner_id, reason


def enrich_with_ai(items: list[str], store_results: dict, scores: dict, winner: str) -> str:
    """
    Optional: call Claude API to generate a natural language summary
    with brand recommendations.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    client = anthropic.Anthropic(api_key=api_key)
    products_summary = "\n".join(
        f"- {item}" for item in items
    )
    scores_summary = "\n".join(
        f"{sid}: price={sc['price']}, delivery={sc['delivery']}, quality={sc['quality']}, total={sc['total']}"
        for sid, sc in scores.items()
    )

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""Shopping list:
{products_summary}

Store scores:
{scores_summary}

Winner: {winner}

Please write a short, professional English summary (3-4 sentences) explaining:
1. Why {winner} was chosen
2. Any notable brand upgrades worth considering (e.g. "for the pasta, Barilla is available on Auchan for only 30 HUF more than the generic brand")
3. Any items that might be better quality at a different store

Be specific and practical. No bullet points, flowing prose."""
        }]
    )
    return resp.content[0].text if resp.content else ""


def run(input_path: str, output_path: str):
    log = lambda m: print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

    log("── Grocery Agent ─────────────────────────────────────────")
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))

    items        = data.get("items_requested", [])
    store_data   = data.get("stores", {})
    all_totals   = {sid: s.get("cart_total", 0) for sid, s in store_data.items()}

    # Score each store
    scores = {}
    for sid, sdata in store_data.items():
        scores[sid] = score_store(sdata, all_totals)
        log(f"  {sid}: total={scores[sid]['total']} "
            f"(price={scores[sid]['price']}, delivery={scores[sid]['delivery']}, quality={scores[sid]['quality']})")

    # Pick winner
    winner, winner_reason = pick_winner(scores, all_totals)
    log(f"  Winner: {winner}")

    # Build product recommendations with brand quality
    recommendations = []
    for item in items:
        for sid, sdata in store_data.items():
            matched = next((p for p in sdata.get("products", []) if p.get("query") == item and p.get("found")), None)
            if matched:
                brand, quality = match_brand_quality(matched.get("name", ""))
                recommendations.append({
                    "item":    item,
                    "store":   sid,
                    "found":   matched.get("name"),
                    "price":   matched.get("price"),
                    "brand":   brand,
                    "quality": quality,
                })

    # AI narrative (optional)
    ai_summary = enrich_with_ai(items, store_data, scores, winner)
    if ai_summary:
        log("  AI summary generated")

    # Delivery slots for winner
    winner_slots = [
        s for s in store_data.get(winner, {}).get("delivery_slots", [])
        if s.get("available")
    ]

    output = {
        "timestamp":     datetime.now().isoformat(),
        "winner":        winner,
        "winner_reason": winner_reason,
        "ai_summary":    ai_summary,
        "scores":        scores,
        "totals":        all_totals,
        "recommendations": recommendations,
        "winner_slots":  winner_slots[:8],
        "all_slots":     {sid: s.get("delivery_slots", []) for sid, s in store_data.items()},
    }

    Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Decision written to {output_path}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="bot_results.json")
    parser.add_argument("--output", default="decision.json")
    args = parser.parse_args()
    run(args.input, args.output)
