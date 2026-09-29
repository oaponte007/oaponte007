"""Turns a plain-English description ("drain a node and back up /home
first", "restart a service that keeps dying") into a ranked list of
candidate templates -- pure keyword overlap against each template's tags,
title, and description, no model, no network. Deterministic and easy to
audit: you can always see exactly why a template scored the way it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .library import Template

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "for", "on", "in",
    "with", "that", "this", "it", "is", "are", "be", "if", "so", "then",
    "i", "want", "need", "would", "like", "please", "script", "make",
    "build", "create", "my", "me", "help", "do", "does", "can", "you",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1}


@dataclass
class Match:
    template: Template
    score: float
    matched_words: set[str]


def rank(description: str, templates: dict[str, Template]) -> list[Match]:
    """Highest score first. A word matching a tag counts double, since tags
    are curated keywords for exactly this purpose; a word matching only
    the free-text title/description counts once. Ties keep library order.
    """
    query_words = _words(description)
    matches: list[Match] = []
    if not query_words:
        return matches

    for tmpl in templates.values():
        tag_words: set[str] = set()
        for tag in tmpl.tags:
            tag_words |= _words(tag)
        text_words = _words(tmpl.title) | _words(tmpl.description)

        matched_tags = query_words & tag_words
        matched_text = query_words & (text_words - tag_words)
        if not matched_tags and not matched_text:
            continue

        score = 2 * len(matched_tags) + len(matched_text)
        matches.append(Match(template=tmpl, score=score, matched_words=matched_tags | matched_text))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches
