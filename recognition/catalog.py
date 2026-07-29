from __future__ import annotations

# Catálogo jerárquico. La clasificación de modelo se hace únicamente dentro de
# la marca detectada, evitando cruces absurdos entre marcas.
MODELS_BY_BRAND: dict[str, list[str]] = {
    "Nike": [
        "Air Force 1 Low", "Air Force 1 Mid", "Dunk Low", "Dunk High",
        "Air Max Plus TN", "Air Max 90", "Air Max 95", "Air Max 97",
        "Air Max 270", "Air Max 720", "Air Max Dn", "Air Max Pulse",
        "Vapormax Plus", "Vapormax Flyknit", "Shox TL", "Shox R4",
        "Cortez", "Blazer Mid", "Pegasus", "Vomero 5", "P-6000",
        "Zoom Vomero", "Air Huarache", "React Vision", "Metcon",
    ],
    "Jordan": [
        "Air Jordan 1 Low", "Air Jordan 1 Mid", "Air Jordan 1 High",
        "Air Jordan 2", "Air Jordan 3", "Air Jordan 4", "Air Jordan 5",
        "Air Jordan 6", "Air Jordan 11", "Air Jordan 12", "Air Jordan 13",
        "Jordan Spizike Low", "Jordan Max Aura", "Jordan Stadium 90",
    ],
    "Adidas": [
        "Samba OG", "Campus 00s", "Gazelle Indoor", "Superstar",
        "Forum Low", "Forum Mid", "NMD R1", "Ultraboost",
        "Response CL", "Ozweego", "Adistar Cushion", "Handball Spezial",
        "Yeezy Boost 350 V2", "Yeezy 500", "Yeezy Boost 700",
        "Yeezy Foam Runner", "Yeezy Slide",
    ],
    "New Balance": [
        "530", "550", "574", "9060", "1906R", "2002R", "327",
        "990", "991", "992", "993", "1080", "Fresh Foam X",
    ],
    "Puma": ["Speedcat OG", "RS-X", "Suede Classic", "Palermo", "Cali", "Mayze"],
    "Asics": ["Gel-Kayano 14", "Gel-NYC", "Gel-1130", "Gel-Lyte III", "GT-2160"],
    "Converse": ["Chuck Taylor All Star Low", "Chuck Taylor All Star High", "Run Star Hike", "Weapon"],
    "Vans": ["Old Skool", "Knu Skool", "Sk8-Hi", "Authentic", "Slip-On"],
    "Reebok": ["Club C 85", "Classic Leather", "Instapump Fury", "Nano X"],
    "Balenciaga": ["Triple S", "Track", "3XL", "Speed Trainer", "Runner", "Cargo"],
    "On": ["Cloud 5", "Cloudmonster", "Cloudtilt", "Cloudswift", "Cloudnova", "Cloudsurfer"],
    "Hoka": ["Clifton", "Bondi", "Speedgoat", "Transport", "Mafate Speed"],
    "Louis Vuitton": ["LV Trainer", "Run Away", "Skate Sneaker", "LV Archlight"],
    "Gucci": ["Rhyton", "Ace", "Screener", "Mac80"],
    "Dior": ["B23", "B27", "B30", "B31 Runner"],
    "Hugo Boss": ["Icelin Runn", "Titanium Runn", "Parkour Runn", "Skylar", "Saturn Lowp"],
    "Amiri": ["MA-1", "Skel Top Low", "Skel Top High", "Bone Runner"],
    "Timberland": ["6-Inch Premium Waterproof Boot", "Euro Hiker", "Field Boot"],
    "Dr. Martens": ["1460 Boot", "2976 Chelsea Boot", "Jadon Boot"],
    "Under Armour": ["Curry", "HOVR", "Charged Assert"],
    "Saucony": ["ProGrid Triumph 4", "Grid Shadow 2", "Ride"],
    "Fila": ["Disruptor II", "Ray Tracer"],
}

BRANDS = list(MODELS_BY_BRAND) + ["Unknown"]

BRAND_ALIASES = {
    "air jordan": "Jordan", "jordan brand": "Jordan", "nb": "New Balance",
    "newbalance": "New Balance", "lv": "Louis Vuitton", "boss": "Hugo Boss",
    "doc martens": "Dr. Martens", "dr martens": "Dr. Martens",
}

GENERIC_MODELS = ["sneaker", "running shoe", "basketball shoe", "high-top sneaker", "ankle boot", "work boot"]
