"""Pull structured fields out of free-text product descriptions."""
import re
from bs4 import BeautifulSoup

_STOP = (r"(?=\s*(?:Common Name|Description|Appearance|Color|Colour|Odou?r|Solubility|Suggested|Recommended|"
         r"Usage|Use Level|Applications?|pH|Shelf Life|Storage|Flashpoint|Vanilla content|Safety Data|SDS|"
         r"California Prop|Do not|This product|Benefits|How to|Directions|Size|Key Ingredients|Features|"
         r"CAS|Origin|Country|Certifications?|Note|Caution|Warning)\b|$|\n)")


def text(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    t = soup.get_text("\n")
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def inci(t):
    """Raw-material INCI line: 'INCI: ...' / 'INCI Name: ...' / 'INCI Nomenclature: ...'."""
    m = re.search(r"\bINCI(?:\s*(?:Name|Names|Nomenclature|Declaration))?\s*[:\-]?\s*(.+?)" + _STOP, t, re.I | re.S)
    if not m:
        return ""
    v = re.sub(r"\s+", " ", m.group(1)).strip(" :.-")
    if not v or re.fullmatch(r"[A-Z]{2,}\d+[A-Z]*", v):       # supplier codes like 'FSS20709EX'
        return ""
    return v[:600]


def ingredient_list(t):
    """Finished-product full ingredient list."""
    pats = [r"(?:Full\s+)?Ingredient(?:s)?\s+List\s*[:\-]?\s*(.+?)(?:\n|$)",
            r"Full\s+Ingredients?\s*[:\-]?\s*(.+?)(?:\n|$)",
            r"\bINCI\b\s*[:\-]?\s*(.+?)(?:\n|$)",
            r"\bIngredients?\s*[:\-]\s*(.+?)(?:\n|$)"]
    for p in pats:
        for m in re.finditer(p, t, re.I):
            v = m.group(1).strip()
            if v.count(",") >= 4:                 # a real list, not "Ingredients: 5 Peptide Complex"
                return re.sub(r"\s+", " ", v)[:4000]
    return ""


_USE = r"(?:use levels?|usage rates?|usage levels?|recommended (?:use|usage|dosage)(?: levels?| rates?)?|suggested use(?: levels?)?|use at|dosage|usage)"


def use_level_text(t):
    """The supplier's own usage sentence, kept verbatim for context (e.g. 'Soap: 1-10% Creams: 0.5-1%')."""
    m = re.search(_USE + r"\s*[:\-]?\s*(.{0,160})", t, re.I | re.S)
    if not m or "%" not in m.group(1)[:120]:
        return ""
    v = re.sub(r"\s+", " ", m.group(1))
    v = re.split(r"\b(?:INCI|Safety Data|SDS|Certificate|Appearance|Solubility|CAS)\b", v)[0]
    return v.strip(" .;:")[:160]


def percent_range(t):
    """'Suggested Use Levels: 1.0 – 10.0%' / 'usage rate: up to 5%' -> (min, max) of the first range."""
    m = re.search(_USE + r"[^%]{0,80}?(?:(\d+(?:\.\d+)?)\s*%?\s*(?:-|–|—|to)\s*)?(?:up to\s*)?(\d+(?:\.\d+)?)\s*%",
                  t, re.I | re.S)
    if not m:
        return None, None
    lo = float(m.group(1)) if m.group(1) else None
    hi = float(m.group(2))
    if hi > 100 or (lo is not None and lo > hi):
        return None, None
    return lo, hi


def ph_range(t):
    m = re.search(r"\bpH\b[^0-9%]{0,45}?(\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{1,2}(?:\.\d+)?)", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if 0 <= a <= 14 and 0 <= b <= 14 and a <= b:
            return a, b
    return None, None


def solubility(t):
    m = re.search(r"Solubility\s*[:\-]?\s*([^\n.]{2,60})", t, re.I)
    if m:
        return m.group(1).strip()
    lt = t.lower()
    if "oil soluble" in lt or "oil-soluble" in lt:
        return "Oil soluble"
    if "water soluble" in lt or "water-soluble" in lt:
        return "Water soluble"
    return ""


def shelf_life_months(t):
    m = re.search(r"Shelf[\s-]?Life\s*[:\-]?\s*(?:approx\.?\s*)?(\d+)\s*(?:-|–|to)?\s*(\d+)?\s*(months|years|month|year)", t, re.I)
    if not m:
        return None
    n = int(m.group(1))  # lower bound of a range: the conservative figure for safety use
    return n * 12 if m.group(3).lower().startswith("year") else n


def size_from_title(title):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|mL|g|oz|fl\.? ?oz|kg|l|L|ea|EA|pcs)\b", title or "")
    return f"{m.group(1)} {m.group(2)}" if m else ""
