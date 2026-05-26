"""Test the 3 chunking strategies + the registry surface."""

from __future__ import annotations

import pytest

from madrigal.chunking import chunk, list_strategies


def test_list_strategies_returns_three() -> None:
    assert list_strategies() == ["none", "paragraph", "sentence"]


def test_none_returns_single_chunk() -> None:
    assert chunk("Hello world.", "none") == ["Hello world."]


def test_none_preserves_whitespace() -> None:
    """`none` is identity; doesn't strip or split. Caller asked for no chunking."""
    text = "  hello\n\nworld  "
    assert chunk(text, "none") == [text]


def test_sentence_basic_three() -> None:
    text = "Hello world. How are you? I am fine!"
    assert chunk(text, "sentence") == ["Hello world.", "How are you?", "I am fine!"]


def test_sentence_single_sentence() -> None:
    assert chunk("Just one sentence.", "sentence") == ["Just one sentence."]


def test_sentence_strips_whitespace_drops_empty() -> None:
    text = "One. Two.   \n\n  Three."
    assert chunk(text, "sentence") == ["One.", "Two.", "Three."]


def test_sentence_empty_text_returns_empty_list() -> None:
    assert chunk("", "sentence") == []
    assert chunk("   \n  ", "sentence") == []


def test_sentence_handles_no_terminal_punctuation() -> None:
    """Trailing fragment without . ! ? is still one chunk."""
    assert chunk("Just a fragment", "sentence") == ["Just a fragment"]


def test_paragraph_basic() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    assert chunk(text, "paragraph") == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]


def test_paragraph_multi_blank_lines() -> None:
    text = "First.\n\n\n\nSecond."
    assert chunk(text, "paragraph") == ["First.", "Second."]


def test_paragraph_single_paragraph() -> None:
    text = "Just one paragraph with multiple sentences. Like this one."
    assert chunk(text, "paragraph") == [text]


def test_paragraph_empty_text() -> None:
    assert chunk("", "paragraph") == []
    assert chunk("\n\n\n", "paragraph") == []


def test_unknown_strategy_raises_with_available_list() -> None:
    with pytest.raises(ValueError, match="unknown chunk strategy"):
        chunk("hello", "lstm-sentence-tokenizer")


def test_unknown_strategy_error_lists_valid_options() -> None:
    with pytest.raises(ValueError) as exc:
        chunk("hello", "nonexistent")
    msg = str(exc.value)
    for valid in ("none", "sentence", "paragraph"):
        assert valid in msg
