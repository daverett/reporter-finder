import re
from typing import List, Optional

KEYWORD_TO_TOPIC = {
    "ai": "ai",
    "artificial intelligence": "ai",
    "machine learning": "machine learning",
    "llm": "ai",
    "openai": "ai",
    "anthropic": "ai",
    "google": "technology",
    "microsoft": "technology",
    "apple": "technology",
    "startup": "startups",
    "startups": "startups",
    "venture": "finance",
    "vc": "finance",
    "antitrust": "antitrust",
    "doj": "politics",
    "sec": "finance",
    "congress": "politics",
    "supreme court": "politics",
    "election": "elections",
    "tariff": "finance",
    "inflation": "finance",
    "cyber": "cybersecurity",
    "ransomware": "cybersecurity",
    "breach": "cybersecurity",
    "climate": "climate",
    "vaccine": "health",
    "health": "health",
    "music": "culture",
    "sports": "sports",
}

def normalize_topics(topics: List[str]) -> List[str]:
    out = []
    seen = set()
    for t in topics or []:
        if not t:
            continue
        n = re.sub(r"\s+", " ", str(t).strip().lower())
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out

def infer_topics_from_text(text: str, extra_hints: Optional[List[str]] = None, max_topics: int = 6) -> List[str]:
    if not text:
        return normalize_topics(extra_hints or [])[:max_topics]
    t = text.lower()
    hits: List[str] = []
    for needle, topic in KEYWORD_TO_TOPIC.items():
        if needle in t:
            hits.append(topic)
    for h in (extra_hints or []):
        if h and h.lower() in t:
            hits.append(h)
    hits = normalize_topics(hits)
    if not hits and extra_hints:
        hits = normalize_topics(extra_hints)
    return hits[:max_topics]
