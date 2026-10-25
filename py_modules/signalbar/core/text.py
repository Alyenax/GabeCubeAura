"""Normalization for saved ambience names."""
import re
import unicodedata

def normalized(text):
    # ASR and Steam metadata may use typographic apostrophes. Convert them
    # before ASCII folding, which otherwise glues j’aimerais / I’d together.
    text = text.casefold().replace('’', "'").replace('‘', "'")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()).split())

