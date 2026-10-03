import pytest

from wwnn.ingest import safety


@pytest.mark.parametrize("title", [
    "Man killed in bizarre llama accident",
    "Police find body was found near giant pumpkin",
    "Shooting at county fair",
    "Two dead after cheese festival",
    "Suspect stabbed neighbour over hedge",
    "Tragic end for record-breaking goose",
    "Bomb scare at potato museum",
    "Victims of the great custard flood",
])
def test_keyword_screen_rejects_taboo(title):
    v = safety.keyword_check(title)
    assert not v.safe and "taboo" in v.reason


@pytest.mark.parametrize("title", [
    "Council spends six weeks debating the colour of a bench",
    "Escaped alpaca elected honorary mayor",
    "Man builds world's largest rubber duck out of other rubber ducks",
    "Town accidentally orders 10,000 traffic cones",
    "Deadline extended for village scarecrow competition",   # 'deadline' must not match 'dead'
    "Diet of pie wins baking championship",                  # 'diet' must not match 'die'
])
def test_keyword_screen_allows_harmless(title):
    assert safety.keyword_check(title).safe


class _Client:
    def __init__(self, harmless, absurdity=7):
        self.calls = 0
        self.out = {"harmless": harmless, "absurdity": absurdity, "reason": "test"}

    def chat_json(self, system, user, schema, model=None, temperature=0.0):
        self.calls += 1
        assert "harmless" in system and temperature == 0.0
        return self.out


def test_llm_can_only_remove_items():
    c = _Client(harmless=True)
    v = safety.screen("Man killed by falling cheese", "", client=c)
    assert not v.safe and c.calls == 0          # keyword reject is final, LLM never consulted


def test_llm_rejects_what_keywords_missed():
    v = safety.screen("Neighbour feud ends in hospital", "", client=_Client(harmless=False, absurdity=2))
    assert not v.safe


def test_llm_scores_absurdity_and_clamps():
    v = safety.screen("Goose appointed to parish council", "", client=_Client(harmless=True, absurdity=42))
    assert v.safe and v.absurdity == 10


def test_heuristic_without_llm():
    v = safety.screen("Bizarre giant potato baffles council", "", client=None)
    assert v.safe and v.absurdity >= 7
