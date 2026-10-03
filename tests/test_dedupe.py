from wwnn.ingest import dedupe


def test_normalize_url_strips_tracking():
    a = dedupe.normalize_url("https://Example.com/story/?utm_source=x&id=5&fbclid=abc#top")
    b = dedupe.normalize_url("https://example.com/story?id=5")
    assert a == b
    assert dedupe.url_hash(a) == dedupe.url_hash(b)


def test_near_duplicate_titles():
    t1 = dedupe.title_hash("Escaped llama leads police on two-hour chase through Swindon")
    t2 = dedupe.title_hash("Escaped llama leads police on a two-hour chase through Swindon")
    t3 = dedupe.title_hash("Council votes to rename roundabout after local cat")
    assert dedupe.is_near_duplicate(t2, [t1])
    assert not dedupe.is_near_duplicate(t3, [t1])
