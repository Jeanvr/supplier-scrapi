import re
import unicodedata


STOPWORDS = {
    "bosch",
    "junkers",
    "caldera",
    "calentador",
    "calentadores",
    "termo",
    "termos",
    "electrico",
    "eléctrico",
    "electric",
    "agua",
    "gas",
    "natural",
    "nat",
    "vertical",
    "horizontal",
    "toma",
    "superior",
    "inferior",
    "condensacion",
    "condensación",
    "mural",
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "y",
    "con",
    "para",
    "por",
    "en",
    "no",
    "nox",
    "bajo",
    "baix",
    "baja",
    "alto",
    "w",
    "kw",
    "mm",
    "l",
}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def normalize_search_text(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""

    replacements = [
        (r"\btr2000t\b", "tronic 2000 t"),
        (r"\btr(\d{4})t\b", r"tronic \1 t"),
        (r"\bt(\d{4})sr\b", r"therm \1 sr"),
        (r"\bt(\d{4})s\b", r"therm \1 s"),
        (r"\btherm\s+6600\s+s/sr\b", "therm 6600 s sr"),
        (r"\b60/100\b", "60 100"),
        (r"\b80/110\b", "80 110"),
        (r"\b80/80\b", "80 80"),
        (r"[^a-z0-9]+", " "),
    ]

    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_spaces(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify(value: object, max_length: int = 80) -> str:
    text = normalize_text(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        return "file"
    return text[:max_length].strip("-") or "file"


def build_name_tokens(name: str) -> list[str]:
    text = normalize_search_text(name)
    tokens = re.findall(r"[a-z0-9]+", text)
    result = []
    for token in tokens:
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        result.append(token)
    return result
