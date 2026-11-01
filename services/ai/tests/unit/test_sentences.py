from trustdesk_ai.rag.sentences import SentenceBuffer


def stream(text: str, step: int = 3) -> list[str]:
    buf = SentenceBuffer()
    out: list[str] = []
    for i in range(0, len(text), step):
        out += buf.feed(text[i : i + step])
    return out + buf.flush()


def test_markers_stay_with_sentence_before_and_after_period():
    text = "We build stores [E1]. Prices start at $1.5k. [E2] Thanks!"
    assert [s.strip() for s in stream(text)] == ["We build stores [E1].", "Prices start at $1.5k. [E2]", "Thanks!"]


def test_bullets_split_on_newlines():
    assert [s.strip() for s in stream("- Starter [E1]\n- Growth [E2]")] == ["- Starter [E1]", "- Growth [E2]"]


def test_urdu_terminator_and_lossless_join():
    text = "ہم ویب سائٹ بناتے ہیں [E1]۔ شکریہ"
    parts = stream(text, step=2)
    assert len(parts) == 2 and "".join(parts) == text


def test_every_step_size_is_lossless():
    text = "One [E1]. Two, e.g. three [E2]!\nFour"
    for step in range(1, 8):
        assert "".join(stream(text, step)) == text
