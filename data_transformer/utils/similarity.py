"""
Similarity calculation utilities.
"""
from typing import Set
import re


def calculate_similarity(text1: str, text2: str, method: str = 'cosine') -> float:
    """
    Calculate similarity between two texts.

    Args:
        text1: First text
        text2: Second text
        method: Similarity method ('cosine', 'jaccard', 'edit_distance')

    Returns:
        Similarity score (0-1, higher means more similar)
    """
    if method == 'cosine':
        return cosine_similarity(text1, text2)
    elif method == 'jaccard':
        return jaccard_similarity(text1, text2)
    elif method == 'edit_distance':
        return normalized_edit_distance(text1, text2)
    else:
        raise ValueError(f"Unknown similarity method: {method}")


def tokenize(text: str) -> list:
    """Simple word tokenization."""
    return re.findall(r'\w+', text.lower())


def cosine_similarity(text1: str, text2: str) -> float:
    """
    Calculate cosine similarity between two texts.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Cosine similarity score (0-1)
    """
    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)

    if not tokens1 or not tokens2:
        return 0.0

    # Build vocabulary
    vocab = set(tokens1 + tokens2)

    # Create frequency vectors
    vec1 = {word: tokens1.count(word) for word in vocab}
    vec2 = {word: tokens2.count(word) for word in vocab}

    # Calculate dot product
    dot_product = sum(vec1[word] * vec2[word] for word in vocab)

    # Calculate magnitudes
    mag1 = sum(vec1[word] ** 2 for word in vocab) ** 0.5
    mag2 = sum(vec2[word] ** 2 for word in vocab) ** 0.5

    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


def jaccard_similarity(text1: str, text2: str) -> float:
    """
    Calculate Jaccard similarity between two texts.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Jaccard similarity score (0-1)
    """
    tokens1 = set(tokenize(text1))
    tokens2 = set(tokenize(text2))

    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union)


def edit_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein edit distance between two strings.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Edit distance (number of edits needed)
    """
    if len(s1) < len(s2):
        return edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def normalized_edit_distance(text1: str, text2: str) -> float:
    """
    Calculate normalized edit distance similarity.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score (0-1, where 1 means identical)
    """
    if not text1 and not text2:
        return 1.0

    max_len = max(len(text1), len(text2))
    if max_len == 0:
        return 1.0

    distance = edit_distance(text1, text2)
    return 1.0 - (distance / max_len)
