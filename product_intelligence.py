#!/usr/bin/env python3
"""
product_intelligence.py
────────────────────────
Comprehensive product quality database + preference/substitution engine.

Quality scores: 1=budget, 2=acceptable, 3=good, 4=very good, 5=premium/exceptional
Sources: Claude training knowledge on brand quality, ingredients, sourcing, reviews.

Usage (standalone):
    from product_intelligence import resolve_item, ProductIntelligence
    pi = ProductIntelligence()
    result = pi.resolve("pasta", user_preference="Barilla")
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Brand:
    name:        str
    score:       int          # 1–5
    notes:       str = ""     # why this score
    available:   list[str] = field(default_factory=list)   # stores where typically found
    price_tier:  str = "mid"  # budget / mid / premium / luxury


@dataclass
class Category:
    name:        str
    keywords:    list[str]
    brands:      list[Brand]
    search_tips: str = ""     # how to search on Hungarian grocery sites
    price_threshold: float = 0.05  # max acceptable price premium for quality upgrade
    # Per-category rationale:
    # Staples (milk, water): 3% — commodity, brand matters less
    # Mid (pasta, rice, canned): 8% — quality difference is real, worth paying
    # Flavour-critical (olive oil, chocolate, coffee): 15% — taste impact is high
    # Protein/fresh (salmon, meat, eggs): 12% — welfare + taste matter a lot
    # Luxury (wine, cheese): 20% — quality range is vast, worth the premium


@dataclass
class ResolvedItem:
    query:            str
    category:         Optional[str]
    preferred_brand:  Optional[str]   # user's explicit preference
    search_term:      str             # what to type into the search box
    recommended:      Optional[Brand] # AI recommendation if no preference
    alternatives:     list[Brand]     # ranked alternatives
    preference_found: bool = False    # was user's preferred brand available?
    upgrade_note:     str = ""        # "X is only 5% more, worth it"


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT QUALITY DATABASE
# ══════════════════════════════════════════════════════════════════════════════


CATEGORIES: list[Category] = [

    # ── SOFT DRINKS ──────────────────────────────────────────────────────────
    Category("soft drinks", ["cola", "coca cola", "pepsi", "fanta", "sprite", "üdítő",
                              "soft drink", "limonádé", "ice tea", "energy drink"],
        brands=[
            Brand("Coca-Cola",       4, "Global benchmark, consistent taste", ["auchan","kifli","tesco"], "mid"),
            Brand("Pepsi",           3, "Good alternative, slightly sweeter", ["auchan","tesco"], "mid"),
            Brand("Fever-Tree",      5, "Premium mixer, natural ingredients", ["kifli"], "premium"),
            Brand("Tesco / Everyday",1, "Budget generic", ["tesco"], "budget"),
        ],
        price_threshold=0.05),

    # ── TÚRÓ / DAIRY ─────────────────────────────────────────────────────────
    Category("túró", ["túró", "túró rudi", "zsírszegény túró", "quark", "cottage cheese",
                       "krémsajt"],
        brands=[
            Brand("Pöttyös Túró Rudi",5, "Hungarian iconic, original gold standard", ["kifli","auchan","tesco"], "mid"),
            Brand("Mizo túró",        4, "Good quality Hungarian quark", ["kifli","auchan","tesco"], "mid"),
            Brand("Tesco / Everyday", 1, "Budget", ["tesco"], "budget"),
        ],
        price_threshold=0.05),

    # ── PET FOOD ─────────────────────────────────────────────────────────────
    Category("pet food", ["macskatáp", "kutyatáp", "kutya snack", "macskaeledel",
                           "kutyaeledel", "állateledel", "cat food", "dog food",
                           "whiskas", "purina", "royal canin", "pedigree"],
        brands=[
            Brand("Royal Canin",     5, "Veterinary-grade, breed-specific nutrition", ["kifli","auchan","tesco"], "premium"),
            Brand("Hill's Science",  5, "Science-based formulas", ["kifli","auchan"], "premium"),
            Brand("Purina Pro Plan", 4, "Professional grade, widely trusted", ["kifli","auchan","tesco"], "mid"),
            Brand("Whiskas",         3, "Acceptable everyday cat food", ["auchan","tesco","kifli"], "mid"),
            Brand("Pedigree",        3, "Standard dog food", ["auchan","tesco"], "mid"),
            Brand("Tesco / Everyday",1, "Budget, low nutritional value", ["tesco"], "budget"),
        ],
        price_threshold=0.12),

    # ── PAPER / HOUSEHOLD ────────────────────────────────────────────────────
    Category("paper", ["papírtörlő", "kitchen roll", "toilet paper", "wc papír",
                        "zsebkendő", "toalettpapír", "papírzsebkendő", "tissue"],
        brands=[
            Brand("Zewa Deluxe",     5, "Premium softness, excellent absorbency", ["auchan","kifli","tesco"], "premium"),
            Brand("Plenty",          4, "Good kitchen roll, strong when wet", ["auchan","tesco"], "mid"),
            Brand("Regina",          3, "Acceptable everyday paper", ["tesco","auchan"], "mid"),
            Brand("Tesco / Everyday",1, "Budget, thin", ["tesco"], "budget"),
        ],
        price_threshold=0.05),

    # ── FLOUR ────────────────────────────────────────────────────────────────
    Category("flour", ["liszt", "flour", "búzaliszt", "rozsliszt", "teljes kiőrlésű",
                        "whole wheat", "rye flour", "sütőpor"],
        brands=[
            Brand("Nagyi Titka",     5, "Hungarian premium flour, finest grind", ["kifli","auchan"], "premium"),
            Brand("Gyermelyi liszt", 4, "Reliable Hungarian brand", ["kifli","auchan","tesco"], "mid"),
            Brand("Tesco / Everyday",2, "Basic, functional", ["tesco"], "budget"),
        ],
        price_threshold=0.05),

    # ── GROOMING / RAZORS ────────────────────────────────────────────────────
    Category("grooming", ["borotva", "razor", "borotvapenge", "borotvahab",
                           "shaving cream", "gillette", "borotvagél", "shaving gel"],
        brands=[
            Brand("Gillette Fusion", 5, "Industry benchmark, smooth precision shave", ["auchan","kifli","tesco"], "premium"),
            Brand("Gillette Mach3",  4, "Reliable classic, excellent value", ["auchan","kifli","tesco"], "mid"),
            Brand("Wilkinson Sword", 4, "Strong competitor, good blades", ["auchan","tesco"], "mid"),
            Brand("Tesco / Everyday",1, "Budget disposable", ["tesco"], "budget"),
        ],
        price_threshold=0.08),

    # ── FROZEN VEGETABLES ────────────────────────────────────────────────────
    Category("frozen", ["mirelit", "fagyasztott", "mirelit borsó", "mirelit zöldség",
                         "frozen peas", "frozen vegetables", "mirelit kukorica",
                         "mirelit brokkoli"],
        brands=[
            Brand("Bonduelle",       5, "French leader, IQF freezing, best quality", ["auchan","kifli","tesco"], "premium"),
            Brand("Iglo",            4, "German quality, reliable frozen range", ["auchan","tesco"], "mid"),
            Brand("McCain",          3, "Standard quality, widely available", ["tesco","auchan"], "mid"),
            Brand("Tesco / Everyday",1, "Budget, acceptable", ["tesco"], "budget"),
        ],
        price_threshold=0.08),

    # ── PASTA ─────────────────────────────────────────────────────────────────
    Category("pasta", ["pasta", "tészta", "spaghetti", "penne", "fusilli",
                       "tagliatelle", "linguine", "rigatoni", "farfalle", "lasagna"],
        brands=[
            Brand("De Cecco",       5, "Bronze-die extrusion, holds al dente perfectly, premium semolina", ["auchan"], "premium"),
            Brand("Rummo",          5, "Slow-dried, exceptional texture, Italian artisan", ["auchan"], "premium"),
            Brand("Garofalo",       5, "Campania origin, organic options, excellent bite", ["auchan", "kifli"], "premium"),
            Brand("Barilla",        4, "Reliable Italian standard, consistent quality, wide range", ["auchan", "kifli", "tesco"], "mid"),
            Brand("La Molisana",    4, "Bronze-die, affordable premium, great value", ["auchan"], "mid"),
            Brand("Pasta Reggia",   3, "Decent everyday pasta, Neapolitan origin", ["tesco"], "mid"),
            Brand("Gyermelyi",      2, "Hungarian, acceptable but softer texture, overcooks easily", ["kifli", "tesco"], "budget"),
            Brand("Alnatura",       4, "Organic, whole wheat options, good quality", ["auchan"], "mid"),
            Brand("Tesco Finest",   3, "Surprisingly decent own-brand premium range", ["tesco"], "mid"),
            Brand("Tesco / Everyday",1,"Budget option, mushes easily", ["tesco"], "budget"),
        ],
        search_tips="Search: 'Barilla spaghetti' or 'De Cecco pasta'", price_threshold=0.08),

    # ── OLIVE OIL ─────────────────────────────────────────────────────────────
    Category("olive oil", ["olive oil", "olívaolaj", "extra virgin", "evoo"],
        brands=[
            Brand("Frantoia",       5, "Sicilian, cold-pressed, exceptional fruity aroma", ["auchan"], "luxury"),
            Brand("Laudemio",       5, "Tuscan, Frescobaldi estate, extraordinary quality", ["auchan"], "luxury"),
            Brand("Podere",         5, "Artisan Tuscan, small batch", ["auchan"], "luxury"),
            Brand("Monini Granfruttato",4,"Consistent premium, widely available", ["auchan","kifli","tesco"], "premium"),
            Brand("Filippo Berio Extra Virgin",4,"Reliable premium, good for everyday cooking", ["tesco","kifli"], "mid"),
            Brand("Bertolli Extra Virgin",3,"Decent everyday EVOO, widely available", ["tesco","kifli"], "mid"),
            Brand("Gallo",          3, "Portuguese origin, acceptable quality", ["tesco"], "mid"),
            Brand("Tesco Extra Virgin",2,"Basic, questionable sourcing", ["tesco"], "budget"),
        ]),

    # ── CHEESE ────────────────────────────────────────────────────────────────
    Category("cheese", ["cheese", "sajt", "mozzarella", "parmesan", "parmezán",
                        "cheddar", "gouda", "brie", "camembert", "gorgonzola",
                        "feta", "ricotta", "mascarpone"],
        brands=[
            Brand("Parmigiano Reggiano DOP",5,"Authentic Parmesan, 24+ month aged, PDO protected", ["auchan","kifli"], "luxury"),
            Brand("Grana Padano DOP",5,"Excellent alternative to Parmesan, milder", ["auchan","kifli"], "premium"),
            Brand("Galbani Mozzarella di Bufala",5,"Buffalo milk, authentic Campanian, superior taste", ["auchan"], "premium"),
            Brand("Président",      4, "French dairy giant, consistently good across types", ["auchan","kifli","tesco"], "mid"),
            Brand("Arla",           4, "Danish quality, good cheddar and gouda", ["kifli","tesco"], "mid"),
            Brand("Kerrygold",      4, "Irish grass-fed, excellent cheddar", ["auchan","kifli"], "mid"),
            Brand("Zott",           3, "German, decent everyday options", ["tesco","kifli"], "mid"),
            Brand("Mizo",           2, "Hungarian, acceptable local option", ["kifli","tesco"], "budget"),
        ]),

    # ── COFFEE ────────────────────────────────────────────────────────────────
    Category("coffee", ["coffee", "kávé", "espresso", "cappuccino", "filter coffee",
                        "coffee beans", "ground coffee", "kávébab"],
        brands=[
            Brand("Illy",           5, "Italian perfection, balanced blend, iconic red tin", ["auchan","kifli"], "premium"),
            Brand("Lavazza Super Crema",5,"Velvety, vanilla notes, excellent espresso", ["auchan","kifli"], "premium"),
            Brand("Kimbo",          5, "Neapolitan roaster, intense authentic espresso", ["auchan"], "premium"),
            Brand("Segafredo",      4, "Italian, bold, reliable quality", ["auchan","tesco"], "mid"),
            Brand("Lavazza Qualità Oro",4,"Classic blend, consistently good", ["auchan","kifli","tesco"], "mid"),
            Brand("Julius Meinl",   4, "Viennese tradition, smooth roast", ["kifli","auchan"], "mid"),
            Brand("Tchibo",         3, "German, reliable everyday option", ["tesco","kifli"], "mid"),
            Brand("Douwe Egberts",  3, "Dutch, mild, widely available", ["tesco"], "mid"),
            Brand("Tesco / Everyday",1,"Budget robusta blend", ["tesco"], "budget"),
        ]),

    # ── MILK & DAIRY ──────────────────────────────────────────────────────────
    Category("milk", ["milk", "tej", "tejet", "whole milk", "teljes tej",
                      "oat milk", "almond milk", "soy milk", "lactose free"],
        brands=[
            Brand("Organic bio (any brand)",4,"Organic certified, better taste and animal welfare", ["auchan","kifli"], "premium"),
            Brand("Natumi",         4, "Organic plant milks, excellent range", ["auchan"], "premium"),
            Brand("Oatly",          4, "Premium oat milk, barista version excellent", ["auchan","kifli"], "premium"),
            Brand("Alpro",          3, "Plant milks, solid quality", ["auchan","kifli","tesco"], "mid"),
            Brand("Parmalat",       3, "Italian UHT, clean taste", ["kifli","tesco"], "mid"),
            Brand("Mizo",           3, "Hungarian standard, decent fresh milk", ["kifli","tesco","auchan"], "mid"),
            Brand("Sole Mizo",      3, "Acceptable everyday option", ["kifli","tesco"], "mid"),
            Brand("Tesco / Everyday",1,"Budget, functional", ["tesco"], "budget"),
        ]),

    # ── EGGS ──────────────────────────────────────────────────────────────────
    Category("eggs", ["eggs", "tojás", "free range", "organic eggs", "bio tojás"],
        brands=[
            Brand("Organic free-range bio",5,"Best welfare, richest yolk, superior taste", ["auchan","kifli"], "premium"),
            Brand("Free-range (szabadtartású)",4,"Better welfare than cage, good yolk colour", ["auchan","kifli","tesco"], "mid"),
            Brand("Barn eggs (mélyalmos)",3,"Acceptable welfare, standard quality", ["tesco","kifli"], "mid"),
            Brand("Caged (ketreces)",1,"Lowest welfare, pale yolk", ["tesco"], "budget"),
        ],
        search_tips="Search: 'bio szabadtartású tojás' for premium", price_threshold=0.15),

    # ── BUTTER ────────────────────────────────────────────────────────────────
    Category("butter", ["butter", "vaj", "unsalted", "salted", "cultured butter"],
        brands=[
            Brand("Kerrygold",      5, "Irish grass-fed, golden colour, exceptional flavour", ["auchan","kifli"], "premium"),
            Brand("Lurpak",         5, "Danish cultured, world-class, great for baking", ["auchan","kifli","tesco"], "premium"),
            Brand("Président",      4, "French, cultured butter, excellent", ["auchan","kifli"], "mid"),
            Brand("Elle & Vire",    4, "Normandy dairy, excellent quality", ["auchan"], "mid"),
            Brand("Anchor",         4, "New Zealand grass-fed, reliable", ["tesco","kifli"], "mid"),
            Brand("Mizo",           3, "Hungarian, functional everyday butter", ["kifli","tesco"], "mid"),
            Brand("Tesco / Everyday",1,"Budget, functional", ["tesco"], "budget"),
        ]),

    # ── YOGURT ────────────────────────────────────────────────────────────────
    Category("yogurt", ["yogurt", "joghurt", "greek yogurt", "görög joghurt",
                        "skyr", "kefir"],
        brands=[
            Brand("Fage Total 0% / 2% / 5%",5,"Greek benchmark, thick, high protein, authentic", ["auchan","kifli"], "premium"),
            Brand("Chobani",        5, "American Greek yogurt excellence", ["auchan"], "premium"),
            Brand("Skyr (any)",     5, "Icelandic, ultra-thick, very high protein", ["auchan","kifli"], "premium"),
            Brand("Liberte Organics",4,"Canadian organic, excellent texture", ["auchan"], "premium"),
            Brand("Activia",        3, "Danone, probiotic focus, decent taste", ["kifli","tesco","auchan"], "mid"),
            Brand("Müller",         3, "German, wide variety, acceptable quality", ["tesco","kifli"], "mid"),
            Brand("Danone",         3, "Standard, widely available", ["tesco","kifli"], "mid"),
            Brand("Tesco / Everyday",1,"Budget, watery texture", ["tesco"], "budget"),
        ]),

    # ── BREAD ─────────────────────────────────────────────────────────────────
    Category("bread", ["bread", "kenyér", "sourdough", "kovászos", "baguette",
                       "rye bread", "rozskenyér", "whole grain", "toast"],
        brands=[
            Brand("Artisan Sourdough (bakery)",5,"Real fermentation, complex flavour, best nutrition", ["auchan","kifli"], "premium"),
            Brand("Mestemacher",    5, "German whole grain specialist, dense nutritious rye", ["auchan","kifli"], "premium"),
            Brand("Lieken Urkorn",  4, "German multi-grain, excellent quality", ["auchan","kifli"], "mid"),
            Brand("Harry's",        3, "French bakery chain, decent quality", ["tesco"], "mid"),
            Brand("Tesco Finest",   3, "Own-brand premium, sometimes decent sourdough", ["tesco"], "mid"),
            Brand("Toast (generic)",1,"Industrial, ultra-processed", ["tesco","kifli"], "budget"),
        ]),

    # ── SALMON / FISH ─────────────────────────────────────────────────────────
    Category("salmon", ["salmon", "lazac", "fish", "hal", "tuna", "tonhal",
                        "sea bass", "sügér", "trout", "pisztráng", "cod"],
        brands=[
            Brand("Faroe Islands farmed",5,"Best farmed salmon, cold clean water, excellent fat content", ["auchan","kifli"], "premium"),
            Brand("Wild Alaska / Pacific",5,"Wild-caught, leaner, exceptional flavour", ["auchan"], "premium"),
            Brand("Scottish farmed ASC",4,"Good quality, sustainable certified", ["auchan","kifli","tesco"], "mid"),
            Brand("Norwegian farmed",3,"Standard farmed, acceptable quality", ["tesco","kifli"], "mid"),
            Brand("Tesco smoked salmon",2,"Budget smoked, acceptable for cooking", ["tesco"], "budget"),
        ]),

    # ── CHOCOLATE ─────────────────────────────────────────────────────────────
    Category("chocolate", ["chocolate", "csokoládé", "dark chocolate", "étcsokoládé",
                           "milk chocolate", "white chocolate", "cocoa", "kakaó"],
        brands=[
            Brand("Valrhona",       5, "French benchmark, terroir-specific, exceptional complexity", ["auchan"], "luxury"),
            Brand("Amedei",         5, "Tuscan artisan, world's finest, Porcelana bean", ["auchan"], "luxury"),
            Brand("Michel Cluizel", 5, "French premium, single-origin mastery", ["auchan"], "luxury"),
            Brand("Green & Black's Organic",4,"Organic, fair trade, excellent dark range", ["auchan","kifli"], "premium"),
            Brand("Lindt Excellence",4,"Swiss, reliable high-cocoa range, widely available", ["auchan","kifli","tesco"], "mid"),
            Brand("Ritter Sport",   3, "German, decent quality, many varieties", ["tesco","kifli"], "mid"),
            Brand("Milka",          2, "Mass-market, Mondelez, artificial flavourings", ["tesco","kifli"], "budget"),
            Brand("Nestlé",         2, "Mass-market, controversy re sourcing", ["tesco"], "budget"),
        ]),

    # ── MINERAL WATER ─────────────────────────────────────────────────────────
    Category("water", ["water", "víz", "mineral water", "ásványvíz", "sparkling",
                       "szénsavas", "still water", "csendes víz"],
        brands=[
            Brand("Füredi Savanyúvíz",5,"Hungarian medicinal mineral, highest mineral content", ["auchan","kifli"], "premium"),
            Brand("Evian",          4, "French Alps, natural mineral, clean taste", ["auchan","kifli","tesco"], "mid"),
            Brand("Perrier",        4, "Premium French sparkling, classic", ["auchan","kifli"], "mid"),
            Brand("San Pellegrino", 4, "Italian premium sparkling", ["auchan","kifli","tesco"], "mid"),
            Brand("Volvic",         3, "French volcanic, clean neutral", ["tesco","kifli"], "mid"),
            Brand("Bonaqua",        2, "Coca-Cola brand, filtered tap water", ["tesco"], "budget"),
            Brand("Tesco / Everyday",1,"Basic, functional", ["tesco"], "budget"),
        ]),

    # ── JUICE ─────────────────────────────────────────────────────────────────
    Category("juice", ["juice", "gyümölcslé", "orange juice", "narancslé",
                       "apple juice", "almalé", "pressed juice"],
        brands=[
            Brand("Innocent",       5, "Cold-pressed, no additives, excellent quality", ["auchan","kifli"], "premium"),
            Brand("Tropicana Pure Premium",4,"Not from concentrate, good quality", ["auchan","kifli","tesco"], "mid"),
            Brand("Rauch",          4, "Austrian, high quality, natural", ["kifli","auchan"], "mid"),
            Brand("Hohes C",        3, "German, decent, from concentrate but fortified", ["tesco","kifli"], "mid"),
            Brand("Tesco / Everyday",1,"From concentrate, added sugars", ["tesco"], "budget"),
        ]),

    # ── MEAT ──────────────────────────────────────────────────────────────────
    Category("meat", ["chicken", "csirke", "beef", "marha", "pork", "sertés",
                      "steak", "mince", "darált", "fillet", "brisket"],
        brands=[
            Brand("Organic free-range",5,"Best welfare, superior flavour, cleaner", ["auchan","kifli"], "premium"),
            Brand("RSPCA / NÉBIH approved",4,"Welfare certified, good quality", ["auchan","kifli"], "mid"),
            Brand("Free-range",     4, "Better than standard, good flavour", ["auchan","kifli","tesco"], "mid"),
            Brand("Standard (RSPCA)",3,"Acceptable quality", ["tesco","kifli"], "mid"),
            Brand("Budget / Value", 1, "Lowest welfare, inferior taste", ["tesco"], "budget"),
        ]),

    # ── WINE ──────────────────────────────────────────────────────────────────
    Category("wine", ["wine", "bor", "red wine", "vörösbor", "white wine",
                      "fehérbor", "rosé", "champagne", "prosecco"],
        brands=[
            Brand("Tokaji Aszú 5-6 puttonyos",5,"Hungarian crown jewel, UNESCO protected, botrytis sweetness", ["auchan","kifli"], "luxury"),
            Brand("Villányi Franc / Cabernet",4,"World-class Hungarian red, Takler, Gere", ["auchan","kifli"], "premium"),
            Brand("Egri Bikavér Superior",4,"Hungarian Bull's Blood premium tier", ["auchan","kifli"], "mid"),
            Brand("Moët & Chandon", 4, "Reliable Champagne benchmark", ["auchan","kifli"], "premium"),
            Brand("Nicolas Feuillatte",3,"Decent entry Champagne", ["auchan"], "mid"),
            Brand("Freixenet",      3, "Spanish cava, decent alternative to prosecco", ["tesco","kifli"], "mid"),
            Brand("Tesco Finest",   2, "Hit and miss, acceptable for cooking", ["tesco"], "budget"),
        ]),

    # ── BEER ──────────────────────────────────────────────────────────────────
    Category("beer", ["beer", "sör", "lager", "ale", "craft beer", "IPA"],
        brands=[
            Brand("Dreher 1854",    4, "Premium Hungarian lager, excellent quality", ["auchan","kifli","tesco"], "mid"),
            Brand("Budvar (Budějovický Budvar)",4,"Czech original, proper lager process", ["auchan","kifli"], "mid"),
            Brand("Pilsner Urquell",4,"Czech pilsner benchmark, Saaz hops", ["auchan","kifli"], "mid"),
            Brand("Heineken",       3, "International standard, reliable", ["tesco","kifli"], "mid"),
            Brand("Kőbányai",       2, "Hungarian budget, acceptable", ["tesco","kifli"], "budget"),
        ]),

    # ── CLEANING / HOUSEHOLD ─────────────────────────────────────────────────
    Category("cleaning", ["detergent", "mosószer", "washing up", "mosogatószer",
                          "fabric conditioner", "öblítő", "surface spray"],
        brands=[
            Brand("Frosch",         5, "Eco-certified, plant-based, excellent performance", ["auchan","kifli"], "premium"),
            Brand("Ecover",         5, "Belgian eco pioneer, biodegradable, effective", ["auchan"], "premium"),
            Brand("Method",         4, "Design-forward eco brand, plant-based", ["auchan","kifli"], "mid"),
            Brand("Ariel",          3, "Reliable performance, not eco-friendly", ["tesco","kifli"], "mid"),
            Brand("Persil",         3, "Standard household cleaner", ["tesco","kifli"], "mid"),
            Brand("Tesco / Everyday",1,"Budget functional", ["tesco"], "budget"),
        ]),

    # ── SNACKS / CHIPS ────────────────────────────────────────────────────────
    Category("snacks", ["chips", "crisps", "snacks", "crackers", "nuts", "diók",
                        "mixed nuts", "vegyes", "popcorn"],
        brands=[
            Brand("Tyrrell's",      5, "Kettle-cooked English crisps, exceptional flavours", ["auchan","kifli"], "premium"),
            Brand("Kettle Brand",   4, "American kettle chips, excellent crunch", ["auchan"], "mid"),
            Brand("Lay's Gourmet", 3, "Better than standard Lay's", ["tesco","kifli"], "mid"),
            Brand("Lay's",          2, "Standard mass-market crisps", ["tesco","kifli"], "budget"),
            Brand("Tesco / Everyday",1,"Budget", ["tesco"], "budget"),
        ]),

    # ── ICE CREAM ─────────────────────────────────────────────────────────────
    Category("ice cream", ["ice cream", "fagylalt", "gelato", "sorbet"],
        brands=[
            Brand("Häagen-Dazs",    5, "High cream content, no air, exceptional density", ["auchan","kifli"], "premium"),
            Brand("Ben & Jerry's",  4, "Chunky mix-ins, fair trade, fun flavours", ["auchan","kifli"], "mid"),
            Brand("Magnum",         3, "Decent premium bar format", ["tesco","kifli"], "mid"),
            Brand("Walls / Streets",2,"Mass market, high air content", ["tesco"], "budget"),
        ]),

    # ── TOMATOES / CANNED ─────────────────────────────────────────────────────
    Category("canned tomatoes", ["tomato", "paradicsom", "canned tomatoes",
                                  "paradicsomkonzerv", "passata", "tomato paste"],
        brands=[
            Brand("Mutti",          5, "Italian benchmark, San Marzano region, superior sweetness", ["auchan","kifli"], "premium"),
            Brand("Cirio",          4, "Classic Italian, consistent quality", ["auchan","kifli","tesco"], "mid"),
            Brand("Cento San Marzano",4,"DOP certified, authentic", ["auchan"], "premium"),
            Brand("Heinz",          3, "Acceptable, widely available", ["tesco","kifli"], "mid"),
            Brand("Tesco / Everyday",1,"Budget, acidic, watery", ["tesco"], "budget"),
        ]),

    # ── RICE ──────────────────────────────────────────────────────────────────
    Category("rice", ["rice", "rizs", "basmati", "jasmine", "arborio",
                      "risotto rice", "brown rice"],
        brands=[
            Brand("Tilda",          5, "Pure Basmati benchmark, aged grain, exceptional fragrance", ["auchan","kifli"], "premium"),
            Brand("Royal Basmati",  4, "Good Basmati, aged, reliable", ["auchan"], "mid"),
            Brand("Garofalo Arborio",4,"Italian risotto rice specialist", ["auchan"], "mid"),
            Brand("Uncle Ben's",    3, "Parboiled, convenient, acceptable", ["tesco","kifli"], "mid"),
            Brand("Tesco / Everyday",1,"Budget, mushy when overcooked", ["tesco"], "budget"),
        ]),

    # ── VEGETABLE / FRUIT (fresh) ─────────────────────────────────────────────
    Category("fresh produce", ["vegetables", "zöldség", "fruit", "gyümölcs",
                                "organic", "bio", "avocado", "avokádó",
                                "tomatoes", "salad"],
        brands=[
            Brand("Organic / Bio certified",5,"No pesticides, better nutrition, superior taste", ["auchan","kifli"], "premium"),
            Brand("Local / seasonal",4,"Fresh, low food miles, supports local farmers", ["auchan","kifli"], "mid"),
            Brand("Standard supermarket",2,"Often picked early, long transport", ["tesco"], "budget"),
        ],
        search_tips="Search: 'bio avokádó' or 'ökológiai' for organic options", price_threshold=0.15),

]


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT INTELLIGENCE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ProductIntelligence:
    """
    Resolves shopping list items with quality recommendations and
    preference handling.
    """

    def __init__(self, price_quality_threshold: float = 0.05):
        self.threshold = price_quality_threshold
        self._index: dict[str, Category] = {}
        self._build_index()

    def _build_index(self):
        for cat in CATEGORIES:
            for kw in cat.keywords:
                self._index[kw.lower()] = cat

    def find_category(self, query: str) -> Optional[Category]:
        q = query.lower().strip()
        # 1. Exact match first
        if q in self._index:
            return self._index[q]
        # 2. Query is a keyword (kw == q)
        for kw, cat in self._index.items():
            if kw == q:
                return cat
        # 3. Query contains keyword as whole word
        for kw, cat in self._index.items():
            if re.search(r'\b' + re.escape(kw) + r'\b', q):
                return cat
        # 4. Keyword contains query as whole word
        for kw, cat in self._index.items():
            if re.search(r'\b' + re.escape(q) + r'\b', kw):
                return cat
        # 5. Partial word match (fallback, min 4 chars)
        words = re.findall(r'\w+', q)
        for word in words:
            if len(word) >= 5:  # increased from 4 to reduce false matches
                for kw, cat in self._index.items():
                    if word == kw or kw.startswith(word) or word.startswith(kw):
                        return cat
        return None

    def find_brand_in_category(self, brand_name: str, category: Category) -> Optional[Brand]:
        bn = brand_name.lower()
        for brand in category.brands:
            if bn in brand.name.lower() or brand.name.lower() in bn:
                return brand
        return None

    def resolve(
        self,
        query: str,
        user_preference: Optional[str] = None,
        store: Optional[str] = None,
    ) -> ResolvedItem:
        """
        Resolve a single shopping item.

        Args:
            query:            Item from shopping list e.g. "pasta"
            user_preference:  Optional brand preference e.g. "Barilla"
            store:            Optional store filter e.g. "auchan"

        Returns:
            ResolvedItem with search term + recommendation
        """
        category = self.find_category(query)

        if category is None:
            # Unknown category — return as-is
            return ResolvedItem(
                query=query,
                category=None,
                preferred_brand=user_preference,
                search_term=f"{user_preference} {query}" if user_preference else query,
                recommended=None,
                alternatives=[],
                preference_found=bool(user_preference),
            )

        # Filter brands by store availability if specified
        available_brands = [
            b for b in category.brands
            if not store or store in b.available or not b.available
        ]
        available_brands.sort(key=lambda b: (-b.score, b.price_tier == "budget"))

        # ── Case 1: User has a preference ────────────────────────────────────
        if user_preference:
            preferred = self.find_brand_in_category(user_preference, category)

            if preferred:
                # Great — use it, but check if there's a meaningful upgrade
                better = next(
                    (b for b in available_brands
                     if b.score > preferred.score and b != preferred),
                    None
                )
                upgrade_note = ""
                threshold_pct = int((category.price_threshold if category else 0.05) * 100)
                if better and better.score >= preferred.score + 1:
                    upgrade_note = (
                        f"Tip: {better.name} (score {better.score}/5) is higher quality than "
                        f"{preferred.name} (score {preferred.score}/5). "
                        f"For {category.name if category else 'this category'}, "
                        f"upgrading is worth it if price difference <={threshold_pct}%."
                    )
                return ResolvedItem(
                    query=query,
                    category=category.name,
                    preferred_brand=user_preference,
                    search_term=f"{preferred.name} {query}",
                    recommended=preferred,
                    alternatives=available_brands[:4],
                    preference_found=True,
                    upgrade_note=upgrade_note,
                )
            else:
                # Preferred brand not in DB or not available in this store
                # Find best available substitute
                best = available_brands[0] if available_brands else None
                return ResolvedItem(
                    query=query,
                    category=category.name,
                    preferred_brand=user_preference,
                    search_term=f"{user_preference} {query}",  # still try the preference first
                    recommended=best,
                    alternatives=available_brands[:4],
                    preference_found=False,
                    upgrade_note=(
                        f"'{user_preference}' not in our quality database. "
                        f"If not found, best substitute: {best.name}." if best else ""
                    ),
                )

        # ── Case 2: No preference — recommend best ────────────────────────────
        if not available_brands:
            return ResolvedItem(
                query=query,
                category=category.name,
                preferred_brand=None,
                search_term=query,
                recommended=None,
                alternatives=[],
                preference_found=False,
            )

        # Recommend best quality (not necessarily most expensive)
        best    = available_brands[0]
        second  = available_brands[1] if len(available_brands) > 1 else None

        upgrade_note = ""
        if second and second.score == best.score:
            upgrade_note = f"{second.name} is equally good — pick whichever is cheaper."
        elif second and best.price_tier == "luxury":
            threshold_pct = int(category.price_threshold * 100)
            upgrade_note = (
                f"Budget tip: {second.name} (score {second.score}/5) is excellent "
                f"value if {best.name} is too expensive. "
                f"Quality upgrade threshold for {category.name}: <={threshold_pct}%."
            )

        return ResolvedItem(
            query=query,
            category=category.name,
            preferred_brand=None,
            search_term=f"{best.name} {query}",
            recommended=best,
            alternatives=available_brands[:4],
            preference_found=False,
            upgrade_note=upgrade_note,
        )

    def resolve_list(
        self,
        items: list[str],
        preferences: Optional[dict[str, str]] = None,
        store: Optional[str] = None,
    ) -> list[ResolvedItem]:
        """
        Resolve a full shopping list.

        Args:
            items:       List of shopping items
            preferences: Dict of {item_keyword: brand} e.g. {"pasta": "Barilla"}
            store:       Target store for availability filtering

        Returns:
            List of ResolvedItems
        """
        prefs = preferences or {}
        results = []

        for item in items:
            # Find matching preference key
            pref = None
            item_lower = item.lower()
            for pref_key, pref_brand in prefs.items():
                if pref_key.lower() in item_lower or item_lower in pref_key.lower():
                    pref = pref_brand
                    break

            resolved = self.resolve(item, user_preference=pref, store=store)
            results.append(resolved)

        return results

    def to_bot_instructions(self, resolved_items: list[ResolvedItem]) -> list[dict]:
        """
        Convert resolved items to search instructions for grocery_bot.py
        """
        instructions = []
        for r in resolved_items:
            instructions.append({
                "original_query": r.query,
                "search_term":    r.search_term,
                "preferred_brand": r.preferred_brand,
                "recommended_brand": r.recommended.name if r.recommended else None,
                "quality_score":  r.recommended.score if r.recommended else None,
                "fallback_terms": [
                    b.name + " " + r.query
                    for b in (r.alternatives[1:3] if r.alternatives else [])
                ],
                "notes": r.upgrade_note,
            })
        return instructions

    def format_summary(self, resolved_items: list[ResolvedItem]) -> str:
        """Human-readable summary of recommendations."""
        lines = ["\n📋 Shopping Intelligence Summary\n" + "─" * 50]
        for r in resolved_items:
            if r.preferred_brand and r.preference_found:
                status = f"✓ Preference: {r.preferred_brand}"
            elif r.preferred_brand and not r.preference_found:
                rec_name = r.recommended.name if r.recommended else "unknown"
                status = f"⚠ '{r.preferred_brand}' not confirmed → trying anyway, fallback: {rec_name}"
            elif r.recommended:
                status = f"★ Recommended: {r.recommended.name} ({r.recommended.score}/5 — {r.recommended.notes[:50]})"
            else:
                status = f"? No recommendation (unknown category)"

            lines.append(f"  {r.query:20s} → {status}")
            if r.upgrade_note:
                lines.append(f"  {'':20s}   💡 {r.upgrade_note}")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def resolve_items(
    items: list[str],
    preferences: Optional[dict[str, str]] = None,
    store: Optional[str] = None,
    verbose: bool = True,
) -> list[dict]:
    """
    One-function interface for grocery_agent.py integration.

    Example:
        results = resolve_items(
            ["pasta", "milk", "chocolate"],
            preferences={"pasta": "Barilla", "chocolate": "Lindt"},
            store="auchan"
        )
    """
    pi = ProductIntelligence()
    resolved = pi.resolve_list(items, preferences=preferences, store=store)
    if verbose:
        print(pi.format_summary(resolved))
    return pi.to_bot_instructions(resolved)


# ══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 55)
    print("  Product Intelligence — Demo")
    print("=" * 55)

    test_items = [
        "spaghetti pasta",
        "milk",
        "eggs",
        "salmon",
        "dark chocolate",
        "olive oil",
        "yogurt",
        "butter",
        "orange juice",
        "beer",
    ]

    test_prefs = {
        "pasta":     "Barilla",    # user knows this brand → use it
        "milk":      "Mizo",       # acceptable but we'll note upgrade
        "chocolate": "Milka",      # we'll suggest Lindt is worth the extra
    }

    results = resolve_items(test_items, preferences=test_prefs, store="auchan")

    print("\n\n🤖 Bot instructions (what grocery_bot.py will search for):\n")
    for r in results:
        print(f"  Search: '{r['search_term']}'")
        if r['fallback_terms']:
            print(f"    Fallbacks: {r['fallback_terms']}")
        if r['notes']:
            print(f"    Note: {r['notes']}")
        print()
