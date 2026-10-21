"""Product category grouping + non-cosmetic filter.

Open Beauty Facts is crowd-sourced and contains some foods, drinks and supplements
(e.g. infant formula, coffee creamer, collagen drinks). Food composition is not a cosmetic,
so those records are dropped. Everything else gets a coarse category_group so apps can
filter (Clay is face-first, then hair).
"""
import re

_SUPPLEMENT = re.compile(r"\b(dietary supplements?|food supplements?|vitamin supplements?|herbal supplements?|supplements?|"
                         r"gumm(y|ies)|capsules?|softgels?|tablets?|antacid)\b", re.I)
_FOOD = re.compile(
    r"\b(foods?|beverages?|drinks?|sodas?|waters|dairies|dairy substitutes?|milk substitutes?|creamers?|"
    r"infant formulas?|baby formulas?|baby foods?|baby milks?|cereals?|breakfasts?|snacks?|meats?|cheeses?|"
    r"fermented milk products|chocolates?|confectioner(y|ies)|spreads?|sauces?|condiments?|groceries|sweeteners?|"
    r"breads?|ciders?|wines?|oatmeal|porridge|fats|vegetable oils?|seeds?)\b", re.I)
# Words that mark a product as applied to skin/hair/teeth (any language seen in Open Beauty Facts)
_TOPICAL_NAME = re.compile(
    r"\b(cr[eè]me|cream|lotion|soap|savon|seife|jab[oó]n|shampoo\w*|conditioner|d[eé]m[eê]lant|balm|baume|balsam|gel|wash|"
    r"serum|s[eé]rum|mask|masque|cleans\w*|nettoyant|spray|spreyi|lip|l[eè]vres|hand|mains|face|visage|body|corps|hair|"
    r"cheveux|capillaire|deodor\w*|d[eé]odor\w*|sun|solaire|apr[eè]s|tooth\w*|dentifrice|mouthwash|huile|oil|beurre|butter|"
    r"vergetures|stretch|massage|bath|bain|douche|shower|scrub|gommage|makeup|maquillage|perfum\w*|parfum|eau de|nail|ongles|"
    r"q10|anti[- ]?(rides|wrinkle|aging|age)|urea|ur[eé]e|hydrat\w*|moistur\w*|keratin|k[eé]ratine|tannkrem|tandpasta|"
    r"crema|viso|labbra|tonico|curls|aloe)\b|pflege|creme|seife|shampoo", re.I)
_TOPICAL_TAG = re.compile(
    r"\b(non food products?|non food produkte|hygiene|cosmetics? (?!products?$)|kosmetik|skin ?care|soin|suncare|"
    r"apres solaires|badezusatz|dentifrices?|toothpastes?|hair|shampoos?|soaps?|savons?|deodorants?|makeup|perfumes?|"
    r"body|face|facial|creams|body milks|lip|nail|pflege|kosmetik)\b", re.I)
GROUPS = [
    ("oral_care", r"tooth ?paste|dentifrice|tandpasta|tannkrem|zahnpasta|mouth ?wash|bain de bouche|mondverzorging|oral care|dental"),
    ("sun_care", r"sun ?screen|suncare|sun care|sun protection|spf|after sun|solaire"),
    ("hair", r"shampoo|shampooing|conditioner|apres-shampo|hair|cheveux|scalp|coiff|dandruff|hair dye"),
    ("makeup", r"make ?up|maquillage|lipstick|mascara|foundation|nail polish|vernis|eyeliner|eyeshadow|blush|concealer|cushion"),
    ("fragrance", r"perfume|parfum|eau de toilette|eau de parfum|cologne|fragrance"),
    ("deodorant", r"deodorant|deodorant|anti ?perspirant|antitranspirant"),
    ("face", r"\bface|facial|visage|serum|toner|essence|ampoule|cleansing (water|oil|balm)|micellar|cleanser|eye cream|"
             r"face mask|sheet mask|moisturi[sz]er|day cream|night cream|anti[- ]?(aging|wrinkle)|acne|blemish|peeling|exfoliat"),
    ("body", r"body|shower|douche|bath|soap|savon|hand cream|hand wash|lotion|body milk|intimate"),
    ("baby", r"\bbaby|bebe|infant"),
]
_GROUPS = [(g, re.compile(p, re.I)) for g, p in GROUPS]


# INCI names that appear on cosmetic labels but never on food/supplement labels
_COSMETIC_INCI = {"aqua", "parfum", "fragrance", "phenoxyethanol", "dimethicone", "cyclopentasiloxane",
                  "sodium laureth sulfate", "sodium lauryl sulfate", "cocamidopropyl betaine", "cetearyl alcohol",
                  "cetyl alcohol", "stearyl alcohol", "methylparaben", "propylparaben", "ethylhexylglycerin",
                  "carbomer", "butylene glycol", "linalool", "limonene", "hexyl cinnamal", "citronellol", "geraniol",
                  "ci 77891", "ci 77491", "sodium fluoride", "hydrated silica", "triethanolamine", "behentrimonium chloride",
                  "cetrimonium chloride", "polyquaternium-10", "ceteareth-20", "glyceryl stearate se", "isopropyl myristate",
                  "paraffinum liquidum", "petrolatum", "alcohol denat", "sodium cocoyl isethionate", "disodium edta",
                  "isobutane", "butane", "propane", "lanolin", "lanoline", "cera alba"}


_TABLET_EXCIPIENTS = {"magnesium stearate", "microcrystalline cellulose", "croscarmellose sodium", "povidone",
                      "crospovidone", "sodium starch glycolate", "hypromellose", "colloidal silicon dioxide",
                      "pregelatinized starch", "corn starch", "gelatin", "gelatine"}


def cosmetic_inci_score(ingredient_keys):
    return sum(1 for k in ingredient_keys if k in _COSMETIC_INCI)


def is_non_cosmetic(name, category, tags, ingredient_keys=()):
    """True only when a record looks like food/drink/supplement AND nothing marks it as topical.
    Ambiguous records are kept (losing a real cosmetic is worse than keeping an odd one)."""
    tag_list = [t.strip() for t in (tags or "").split(";") if t.strip()] + [category or ""]
    name = name or ""
    if re.search(r"\b(infant formula|baby formula|coffee creamer|milk creamer|protein shake|meal replacement)\b", name, re.I):
        return True
    if cosmetic_inci_score(ingredient_keys) >= 1:     # label uses cosmetic INCI -> it's a cosmetic
        return False
    # oral medicines / supplements: tablet excipients, medicine tags, or a dose-form name
    if sum(1 for k in ingredient_keys if k in _TABLET_EXCIPIENTS) >= 2:
        return True
    if any(re.search(r"\b(medicines?|medicaments?|m[eé]dicaments?|drugs?|arzneimittel)\b", t, re.I) for t in tag_list) \
            and not any(re.search(r"tooth|dentifrice|dermatolog|cream|cr[eè]me|ointment|pommade", t, re.I) for t in tag_list):
        return True
    if re.search(r"\b(gumm(y|ies)|capsules?|softgels?|tablets?|lozenges?|collagen peptides|allergy (relief|remedy)|"
                 r"loratadine|cetirizine|prednisone|antihistamine)\b", name, re.I):
        return True
    if any(re.search(r"external use|usage externe|usage externe|cire d abeille|huile d amande", k) for k in ingredient_keys):
        return False
    supplement = any(_SUPPLEMENT.search(t) for t in tag_list)
    food = any(_FOOD.search(t) for t in tag_list)
    if not (supplement or food):
        return False
    if any(_TOPICAL_TAG.search(t) for t in tag_list):
        return False
    if supplement:
        # supplements are dropped unless the name says it is applied to the body ('oil' alone isn't enough)
        return not re.search(_TOPICAL_NAME.pattern.replace("huile|oil|", ""), name, re.I)
    return not _TOPICAL_NAME.search(name)


def group(name, category, tags):
    text = " ".join([category or "", tags or "", name or ""])
    for g, rx in _GROUPS:
        if rx.search(text):
            return g
    return "other"
