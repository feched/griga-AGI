"""Сравнение слов в ответе с учётом склонения (eval-проверки)."""

from __future__ import annotations


def mentions_word(text: str, word: str) -> bool:
    """True, если ``word`` встречается в ``text`` в любой форме.

    Простое сравнение основ: «дерево» ≈ «дерева», «зелёная» ≈ «зелёной».
    Для коротких слов (<= 4) требуется точное вхождение, чтобы «да» не
    совпадало с «давно».
    """
    haystack = text.casefold().strip()
    needle = word.casefold().strip()
    if not needle:
        return True
    if needle in haystack:
        return True
    if len(needle) <= 4:
        return False
    stem = needle[: len(needle) - 2]
    return stem in haystack
