from trustdesk_ai.ingestion.hashing import content_hash, normalize_text


def test_whitespace_and_unicode_normalization_do_not_change_hash():
    assert content_hash("Hello   world\n") == content_hash(" Hello world")
    assert content_hash("ﬁle") == content_hash("file")  # NFKC ligature


def test_real_changes_change_hash():
    assert content_hash("Price: 100") != content_hash("Price: 200")


def test_normalize_text():
    assert normalize_text("  a\t\nb ") == "a b"
    assert len(content_hash("x")) == 64
