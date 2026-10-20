from veille.writer import editorial_problems


def test_sample_passes(sample_content):
    assert editorial_problems(sample_content, 5, 8) == []


def test_flags_banned_phrases_emojis_and_slide_count(sample_content):
    content = sample_content.model_copy(deep=True)
    content.threads.post = "This is a game-changer 🚀"
    content.slides[0].heading = "x" * 80
    problems = "\n".join(editorial_problems(content, 7, 8))
    assert "game-changer" in problems
    assert "no emojis" in problems
    assert "between 7 and 8 slides" in problems
    assert "heading is 80 chars" in problems


def test_flags_hashtags_and_long_code(sample_content):
    content = sample_content.model_copy(deep=True)
    content.threads.post = "Postgres queues #backend"
    content.slides[2].code = "\n".join(["x"] * 20)
    problems = "\n".join(editorial_problems(content, 5, 8))
    assert "no hashtags" in problems
    assert "code must fit" in problems
