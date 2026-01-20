from typing import List

def parse_keywords(s: str) -> List[str]:
    if not s:
        return []
    raw = [p.strip() for chunk in s.split(",") for p in chunk.split() if p.strip()]
    seen, out = set(), []
    for w in raw:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(w)
    return out

def parse_csv_locations(s: str) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]
