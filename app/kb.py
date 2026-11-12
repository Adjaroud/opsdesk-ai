"""Small, explainable lexical retrieval: accent folding + title-weighted TF/IDF."""
import math
import re
import unicodedata
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb"
STOP = {"le", "la", "les", "de", "des", "du", "un", "une", "mon", "ma", "mes", "je", "a", "au", "et", "en", "plus", "pour", "ne", "pas", "comment"}


def tokens(text):
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+", folded) if t not in STOP]


def search(query, directory=KB_DIR):
    docs = []
    for path in sorted(Path(directory).glob("*.md")):
        raw = path.read_text(encoding="utf-8")[:5000]
        title = raw.splitlines()[0].lstrip("# ")
        docs.append({"id": path.stem, "title": title, "excerpt": raw[:1800]})
    terms = set(tokens(query))
    scored = []
    for doc in docs:
        body = tokens(doc["excerpt"])
        title = tokens(doc["title"])
        score = 0.0
        for term in terms:
            df = sum(term in tokens(d["excerpt"]) for d in docs)
            tf = body.count(term) + 3 * title.count(term)
            score += (1 + math.log(tf) if tf else 0) * (1 + math.log((1 + len(docs)) / (1 + df)))
        if score:
            scored.append({**doc, "score": round(score, 3)})
    return sorted(scored, key=lambda d: (-d["score"], d["id"]))[:3]
