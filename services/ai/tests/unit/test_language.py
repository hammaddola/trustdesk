import pytest

from trustdesk_ai.rag.language import detect_language, text_direction, tsv_config_for

URDU = "آپ کی خدمات کیا ہیں؟"  # "What are your services?"


@pytest.mark.parametrize(
    "text,lang",
    [
        ("What services do you offer for small businesses?", "en"),
        (URDU, "ur"),
        ("Aap ki services kya hain?", "ur-Latn"),
        ("website banane ka kitna kharcha hai", "ur-Latn"),
        ("hi", "en"),
        ("", "en"),
    ],
)
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_direction_and_tsv_config():
    assert text_direction("ur") == "rtl" and text_direction("ur-Latn") == "ltr" and text_direction("en") == "ltr"
    assert tsv_config_for("en") == "english" and tsv_config_for("ur") == "simple"
