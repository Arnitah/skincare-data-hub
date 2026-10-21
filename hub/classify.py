"""Product classification: is it a cosmetic at all, and which care area is it?

Open Beauty Facts is crowd-sourced and contains some food, supplements, household cleaners and
pet products. Those are excluded (food composition is not a cosmetic; see the atlas rules).
"""
import re

# Category tags that mean "not a personal-care cosmetic"
_NON_COSMETIC_TAG = re.compile(
    r"(?<!non )\bfoods?\b|beverage|\bdrinks?\b|dietary supplement|\bsupplements?\b|\bvitamins\b|snack|spreads?\b|"
    r"condiment|cheese|bread|chocolate|confection|sweetener|cereal|canned|sauces?\b|fermented foods|dairy substitute|"
    r"\bmeat\b|oatmeal$|household|laundry|cleaning|\bdetergents?\b|dishwash|dishwasher|antacid|pet food|"
    r"\bcapsules\b|medicines?\b|medication", re.I)

# Product names that are clearly not cosmetics, whatever the category says
_NON_COSMETIC_NAME = re.compile(
    r"laundry|lessive|dish ?wash|dishwasher|vaisselle|antacid|melatonin|gummies|\bcapsules?\b|electrolyte|"
    r"infant formula|baby formula|toilet bowl|floor cleaner|all[- ]purpose cleaner|"
    r"\bfor (dogs?|cats?|pets?)\b|\b(dog|cat|pet) shampoo|banana oatmeal|collagen peptides", re.I)

_AREAS = [
    ("oral", r"tooth|dental|mouthwash|mouth wash|denti|oral care|zahn"),
    ("fragrance", r"perfume|parfum|eau de (toilette|parfum|cologne)|fragrance|cologne|body mist"),
    ("makeup", r"makeup|make-up|maquillage|nail|mascara|foundation|lipstick|lip cosmetic|lip gloss|eyeliner|eye shadow|concealer|blush|powder"),
    ("hair", r"hair|shampoo|conditioner|scalp|cheveu|coiff|dandruff|capill"),
    ("sun", r"sun|solaire|spf"),
    ("face", r"face|facial|visage|serum|toner|essence|ampoule|eye cream|eye patch|mask|cleansing (water|oil|balm|foam)|micellar|anti[- ]?(aging|wrinkle)|day cream|night cream|acne|blemish|pore|peel"),
    ("body", r"body|shower|bath|soap|savon|deodorant|anti[- ]?perspirant|hand cream|hand wash|douche|lotion|shaving|aftershave|wipes|intimate|feet|foot"),
    ("lip", r"lip balm|lip care|baume"),
]
_AREA_RX = [(a, re.compile(p, re.I)) for a, p in _AREAS]


def is_cosmetic(name, tags):
    """False when tags or name clearly indicate food, supplement, household or pet product."""
    for t in (tags or "").split("; "):
        if t and _NON_COSMETIC_TAG.search(t):
            return False
    return not _NON_COSMETIC_NAME.search(name or "")


def product_area(name, category, tags=""):
    """skin areas: face / body / sun / lip; plus hair, makeup, fragrance, oral; '' when unknown."""
    text = " ".join([category or "", tags or "", name or ""])
    for area, rx in _AREA_RX:
        if rx.search(text):
            return area
    return ""
