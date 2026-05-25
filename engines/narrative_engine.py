NARRATIVE_KEYWORDS = {
    "AI": ["AI", "AGIX", "FET", "TAO", "ARTIFICIAL", "INTELLIGENCE"],
    "RWA": ["RWA", "REAL", "ASSET", "ONDO", "TOKENIZED"],
    "DePIN": ["DEPIN", "HNT", "IOT", "RENDER", "RNDR"],
    "Gaming": ["GAME", "GAMING", "PLAY", "GALA", "IMX"],
    "Meme": ["PEPE", "DOGE", "SHIB", "INU", "FLOKI", "BONK", "WIF"],
    "L2": ["L2", "LAYER", "ARB", "OP", "BASE", "ZK"],
    "DeFi": ["DEFI", "SWAP", "DEX", "LEND", "AAVE", "UNI"],
}

RISK_KEYWORDS = ["SCAM", "RUG", "PONZI", "SAFE", "MOON", "100X", "ELON"]


class NarrativeEngine:
    def tag(self, candidate):
        text = f"{candidate.symbol} {candidate.name}".upper()
        tags = []
        for tag, words in NARRATIVE_KEYWORDS.items():
            if any(word in text for word in words):
                tags.append(tag)
        candidate.narrative_tags = sorted(set(tags))
        if any(word in text for word in RISK_KEYWORDS):
            candidate.risks.append("ryzykowne słowa kluczowe w nazwie/symbolu")
        return candidate
