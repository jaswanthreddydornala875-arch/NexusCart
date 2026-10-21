"""Small text helpers shared by the shopping assistant."""
import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS


def search_terms(text):
    """Return meaningful lowercase tokens for converting assistant requests to searches."""
    return [token for token in re.findall(r"[a-z0-9]+", str(text).lower())
            if token not in ENGLISH_STOP_WORDS]
