"""INCI parsing and normalisation.

INCI names are the one identifier shared across countries, so every ingredient in the hub
is matched on a normalised INCI key (plus CAS where a source publishes it).
"""
import re
import unicodedata

# Common cross-region synonyms -> one key (EU "Aqua" vs US "Water", etc.)
SYNONYMS = {
    "aqua": "water", "eau": "water", "aqua water": "water", "water aqua": "water", "aqua eau": "water",
    "water aqua eau": "water", "purified water": "water", "deionized water": "water",
    "parfum": "fragrance", "fragrance parfum": "fragrance", "parfum fragrance": "fragrance",
    "aroma": "flavor", "flavour": "flavor",
    "tocopherol vitamin e": "tocopherol", "vitamin e": "tocopherol",
    "glycerine": "glycerin",
}

_MAY_CONTAIN = re.compile(r"\b(may contain|peut contenir|\+/-)\b.*$", re.I)


def key(name):
    """Normalised matching key for one INCI name."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\*+|®|™|\(tm\)|\(r\)", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)          # drop "(Mango)" style common names
    s = s.replace("/", " ")
    s = re.sub(r"[^a-z0-9,\-\. ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-,")
    words = set(s.split())
    if words and words <= {"aqua", "water", "eau", "purified", "deionized", "deionised", "distilled"}:
        return "water"
    if words and words <= {"parfum", "fragrance", "perfume"}:
        return "fragrance"
    return SYNONYMS.get(s, s)


def split_list(text):
    """Split a full ingredient list (comma separated, commas inside brackets kept)."""
    if not text:
        return []
    t = re.sub(r"\s+", " ", str(text)).strip()
    t = re.sub(r"^(full\s+)?(ingredients?|ingr[eé]dients|inci( name| names| nomenclature)?|ingredient list)\s*[:\-]?\s*", "", t, flags=re.I)
    t = _MAY_CONTAIN.sub("", t)
    parts, depth, cur = [], 0, ""
    for i, ch in enumerate(t):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        digit_comma = ch == "," and 0 < i < len(t) - 1 and t[i - 1].isdigit() and t[i + 1].isdigit()
        if ch in ",;•·" and depth == 0 and not digit_comma:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    out = []
    for p in parts:
        p = p.strip(" .:*")
        if 1 < len(p) < 160:
            out.append(p)
    return out


_JUNK = re.compile(r"www\.|https?:|@|\?|\b(made in|distribut|importer|imported|expiry|exp\.|batch|lot|tel|phone|"
                   r"service|consumer|contact|warning|caution|avoid|keep out|use by|best before|tested|for external)\b", re.I)


def looks_valid(name):
    """Heuristic: is this string plausibly one ingredient name (not label boilerplate / OCR noise)?"""
    if not name or len(name) > 90 or len(name.split()) > 10:
        return False
    if re.fullmatch(r"(?:CI|C\.I\.)\s*\d{5}(?:\s*\(.*\))?", name.strip(), re.I):   # colour index numbers
        return True
    if _JUNK.search(name) or ":" in name:
        return False
    letters = sum(c.isalpha() for c in name)
    if letters < 3 or letters / len(name) < 0.55:
        return False
    return sum(ord(c) < 128 for c in name) / len(name) > 0.8


def split_blend(inci):
    """Raw-material INCI blends: 'Glycerin (and) Water (and) Larix ...' -> components."""
    if not inci:
        return []
    bits = re.split(r"\s*(?:\(and\)|\band\b|&|,|;|\+)\s*", inci, flags=re.I)
    return [b.strip(" .") for b in bits if b and len(b.strip()) > 1]
