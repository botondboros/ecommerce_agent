🛒 Grocery Agent
> AI-powered weekly grocery comparison across Kifli.hu, Auchan Online and Tesco Online  
> Scrapes prices → AI scores stores → fills cart automatically → visual dashboard
---

Every week, this agent:
- Takes your shopping list as input
- Scrapes all 3 Hungarian online grocery stores simultaneously (Playwright)
- Scores each store across 4 dimensions — price, delivery, quality, coverage
- Uses Claude API to generate a natural-language summary and winner rationale
- Fills the winning store's cart automatically
- Renders a visual HTML dashboard with the full comparison

Result: You open the browser, review the pre-filled cart, and click pay.
---
Architecture
```
run.py                      ← pipeline entry point
├── product_intelligence.py ← brand quality DB (29 categories, 200+ brands)
├── grocery_bot.py          ← Playwright scraper (Kifli / Auchan / Tesco)
├── grocery_agent.py        ← 4-dimension scoring + Claude API decision layer
├── cart_filler.py          ← Playwright cart automation
└── build_results.py        ← embeds JSON into HTML dashboard

setup_bot_profile.py        ← one-time: save login sessions to Chrome profile
setup_scheduler.py          ← register Windows Task Scheduler for weekly runs
```
---
Scoring model

- Dimension	Weight	Source
- Price	35%	scraped cart total (fallback: market knowledge base)
- Delivery	30%	scraped slot availability + speed baseline
- Quality	20%	brand quality DB × store premium multiplier
- Coverage	15%	% of items found × category breadth score

---
Tech stack

- Python 3.12+
- Playwright — browser automation (Chromium)
- Claude API (`claude-sonnet-4`) — store scoring rationale + shopping intelligence
- Vanilla HTML/CSS/JS — results dashboard (no framework)
- python-dotenv — credentials management
- Windows Task Scheduler — weekly automation
---
Setup
1. Install dependencies
```bash
pip install playwright python-dotenv anthropic
playwright install chromium
```
2. Configure credentials
```bash
cp .env.example .env
# fill in your store logins and Anthropic API key
```
3. One-time browser profile setup
```bash
python setup_bot_profile.py
# Opens Chrome — log in to Kifli, Auchan, Tesco manually
# Sessions are saved to bot_chrome_profile/ for reuse
```
4. Run
```bash
python run.py "pasta, tej, tojás, vaj, kávé, lazac, túró rudi, papírtörlő"
python build_results.py   # opens visual dashboard
```
5. Weekly automation (Windows)
```bash
python setup_scheduler.py --day MON --time 09:00
```
---
Built by Botond Boros · March 2025
