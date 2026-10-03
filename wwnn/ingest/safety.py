"""HARD taboo filter: no real violent crime, gore or deaths. Harmless absurd nonsense only.

Applied twice: (1) a conservative keyword screen on every scraped item and archive import,
(2) an LLM classifier (Ollama, JSON output) on whatever survives the keywords. The LLM can
only *remove* items, never re-admit something the keyword screen rejected. Generated
scripts are screened again by ``wwnn.script.lint``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TABOO_PATTERNS = [
    r"kill(?:s|ed|er|ers|ing)?", r"murder\w*", r"homicid\w*", r"manslaughter", r"slaughter\w*",
    r"dead", r"deaths?", r"die[sd]?", r"dying", r"fatal\w*", r"corpses?", r"bod(?:y|ies) (?:was |were )?found",
    r"human remains", r"decapitat\w*", r"behead\w*", r"stab(?:s|bed|bing)?", r"shooting", r"shooter",
    r"shot dead", r"(?:was|were|been) shot", r"gunshot\w*", r"gunm[ae]n", r"gunfire", r"massacre\w*",
    r"terror\w*", r"bomb(?:s|ed|ing|ings)?", r"explosions?", r"wars?", r"invasion", r"airstrikes?",
    r"assault\w*", r"rap(?:e|ed|ist|ists)", r"sexual\w*", r"abus(?:e|ed|er|ive)", r"molest\w*",
    r"kidnap\w*", r"abduct\w*", r"hostages?", r"suicid\w*", r"overdos\w*", r"drown\w*", r"gor[ey]",
    r"blood\w*", r"injur\w*", r"wound(?:s|ed)?", r"maim\w*", r"mutilat\w*", r"tortur\w*",
    r"execut(?:ed|ion|ions)", r"victims?", r"funeral\w*", r"obituar\w*", r"tragic\w*", r"traged\w*",
    r"violen(?:t|ce)", r"lynch\w*", r"genocide", r"poison(?:ed|ing)", r"strangl\w*", r"arson",
    r"manhunt", r"perish\w*", r"casualt\w*", r"autopsy", r"morgue", r"cannibal\w*", r"carnage",
]
_TABOO_RE = re.compile(r"\b(?:" + "|".join(TABOO_PATTERNS) + r")\b", re.IGNORECASE)


@dataclass
class Verdict:
    safe: bool
    reason: str
    absurdity: int | None = None


def keyword_check(text: str) -> Verdict:
    hits = sorted({m.group(0).lower() for m in _TABOO_RE.finditer(text or "")})
    if hits:
        return Verdict(False, "taboo keywords: " + ", ".join(hits[:6]))
    return Verdict(True, "keyword screen passed")


CLASSIFIER_SCHEMA = {
    "type": "object",
    "required": ["harmless", "absurdity", "reason"],
    "properties": {
        "harmless": {"type": "boolean"},
        "absurdity": {"type": "integer", "minimum": 0, "maximum": 10},
        "reason": {"type": "string"},
    },
}

CLASSIFIER_SYSTEM = """You screen news items for a comedy news show that ONLY covers harmless, absurd nonsense.
Set harmless=false if the item involves ANY of: a real death, a killing, violent crime, physical
assault, gore or serious injury, abuse, terrorism, war, disasters with victims, suicide, serious
illness, or mocking a private individual's misfortune. When in doubt, harmless=false.
absurdity: 0 = mundane, 10 = gloriously ridiculous (giant vegetables, bureaucratic farce, animals
behaving like civil servants). Reply only with the JSON object."""


def llm_check(client, title: str, description: str, model: str | None = None) -> Verdict:
    out = client.chat_json(CLASSIFIER_SYSTEM, f"Title: {title}\nSummary: {description or '(none)'}",
                           CLASSIFIER_SCHEMA, model=model, temperature=0.0)
    absurdity = max(0, min(10, int(out.get("absurdity", 0))))
    return Verdict(bool(out.get("harmless")), "llm: " + str(out.get("reason", ""))[:300], absurdity)


ABSURD_HINTS = re.compile(
    r"\b(?:weird|bizarre|odd|strange|giant|record|world'?s (?:largest|biggest|smallest)|llama|goose|"
    r"geese|duck|alpaca|cheese|potato|pumpkin|mistak\w*|accidental\w*|council|bureaucra\w*|robot|"
    r"escaped|loose|wrong|baffl\w*|unusual|surpris\w*|competition|championship)\b", re.IGNORECASE)


def heuristic_absurdity(text: str) -> int:
    """Fallback score when no LLM is available (dry runs)."""
    return min(10, 3 + 2 * len(ABSURD_HINTS.findall(text or "")))


def screen(text_title: str, text_desc: str, client=None, model: str | None = None) -> Verdict:
    kw = keyword_check(f"{text_title}\n{text_desc or ''}")
    if not kw.safe:
        return kw
    if client is None:
        return Verdict(True, kw.reason + "; no LLM classifier", heuristic_absurdity(f"{text_title} {text_desc}"))
    v = llm_check(client, text_title, text_desc, model)
    return v
