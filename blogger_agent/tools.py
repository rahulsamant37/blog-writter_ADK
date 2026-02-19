import glob
import os
import re
from collections import Counter


_VOWELS_RE = re.compile(r"[aeiouy]+", re.IGNORECASE)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _split_into_paragraphs(text: str) -> list[str]:
    text = (text or "").replace("\r\n", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    return paragraphs


def _split_into_sentences(text: str) -> list[str]:
    text = _normalize_whitespace(text)
    if not text:
        return []
    # Conservative heuristic sentence splitter.
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _tokenize_words(text: str) -> list[str]:
    # Keeps apostrophes in contractions.
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or "")


def _estimate_syllables_in_word(word: str) -> int:
    word = (word or "").lower()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0

    # Very short words tend to be 1 syllable.
    if len(word) <= 3:
        return 1

    # Count vowel groups.
    vowel_groups = _VOWELS_RE.findall(word)
    syllables = len(vowel_groups)

    # Remove a syllable for silent trailing 'e' (but keep 'le').
    if word.endswith("e") and not word.endswith("le"):
        syllables -= 1

    # Add syllable for consonant + 'le' endings (e.g., "table").
    if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiouy":
        syllables += 1

    # Ensure at least 1.
    return max(1, syllables)


def _count_syllables(words: list[str]) -> int:
    return sum(_estimate_syllables_in_word(w) for w in words)


def _flesch_reading_ease(word_count: int, sentence_count: int, syllable_count: int) -> float:
    if word_count <= 0 or sentence_count <= 0:
        return 0.0
    return 206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (syllable_count / word_count)


def _flesch_kincaid_grade(word_count: int, sentence_count: int, syllable_count: int) -> float:
    if word_count <= 0 or sentence_count <= 0:
        return 0.0
    return 0.39 * (word_count / sentence_count) + 11.8 * (syllable_count / word_count) - 15.59


_SIMPLE_REPLACEMENTS: dict[str, str] = {
    "utilize": "use",
    "leverage": "use",
    "facilitate": "help",
    "demonstrate": "show",
    "approximately": "about",
    "numerous": "many",
    "additional": "extra",
    "commence": "start",
    "terminate": "end",
    "obtain": "get",
    "required": "needed",
    "sufficient": "enough",
    "prior to": "before",
    "subsequent": "later",
    "in order to": "to",
}


def _apply_simple_replacements(text: str) -> tuple[str, Counter]:
    """Apply small, safe simplifications (no external thesaurus).

    Returns (new_text, counts_by_phrase).
    """
    counts: Counter = Counter()
    updated = text
    for phrase, simple in _SIMPLE_REPLACEMENTS.items():
        # Whole-word / phrase matching, case-insensitive.
        pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
        matches = pattern.findall(updated)
        if matches:
            counts[phrase] += len(matches)
            updated = pattern.sub(simple, updated)
    return updated, counts


def readability_scorer(
    text: str,
    max_sentence_words: int = 25,
    max_paragraph_words: int = 120,
    max_complex_sentences: int = 10,
) -> dict:
    """Readability scoring + actionable suggestions.

    Includes:
    - Flesch Reading Ease
    - Flesch-Kincaid Grade
    - Simplification suggestions for complex sentences
    - Paragraph length/structure analysis
    """
    original_text = text or ""
    simplified_text, replacement_counts = _apply_simple_replacements(original_text)

    sentences = _split_into_sentences(original_text)
    words = _tokenize_words(original_text)
    syllables = _count_syllables(words)

    word_count = len(words)
    sentence_count = max(1, len(sentences)) if word_count else 0
    paragraph_list = _split_into_paragraphs(original_text)
    paragraph_count = len(paragraph_list)

    reading_ease = _flesch_reading_ease(word_count, sentence_count, syllables)
    grade_level = _flesch_kincaid_grade(word_count, sentence_count, syllables)

    complex_sentences: list[dict] = []
    for idx, s in enumerate(sentences, start=1):
        s_words = _tokenize_words(s)
        s_word_count = len(s_words)
        if s_word_count <= max_sentence_words:
            continue

        suggestions: list[str] = [
            f"Sentence is {s_word_count} words; consider splitting into 2–3 shorter sentences.",
        ]
        comma_count = s.count(",")
        semicolon_count = s.count(";")
        if comma_count >= 2 or semicolon_count >= 1:
            suggestions.append("Try splitting at commas/semicolons where ideas change.")
        if re.search(r"\b(which|that|because|however|therefore|although|whereas)\b", s, re.IGNORECASE):
            suggestions.append("Consider removing or rewriting subordinate clauses (e.g., 'which/that/because') for clarity.")

        # Provide a naive split suggestion.
        split_candidate = re.split(r"\s*(?:;|—|--)\s*", s)
        if len(split_candidate) == 1 and "," in s:
            split_candidate = [p.strip() for p in s.split(",") if p.strip()]
        if len(split_candidate) >= 2:
            proposed = ". ".join(split_candidate)
            proposed = proposed if proposed.endswith((".", "!", "?")) else proposed + "."
        else:
            proposed = None

        truncated_sentence = s if len(s) <= 400 else (s[:397] + "...")
        entry = {
            "index": idx,
            "word_count": s_word_count,
            "sentence": truncated_sentence,
            "suggestions": suggestions,
        }
        if proposed:
            entry["split_suggestion"] = proposed if len(proposed) <= 600 else (proposed[:597] + "...")

        complex_sentences.append(entry)
        if len(complex_sentences) >= max_complex_sentences:
            break

    paragraphs: list[dict] = []
    for idx, p in enumerate(paragraph_list, start=1):
        p_sentences = _split_into_sentences(p)
        p_words = _tokenize_words(p)
        p_word_count = len(p_words)
        flags: list[str] = []
        suggestion = None

        if p_word_count > max_paragraph_words:
            flags.append(f"Long paragraph ({p_word_count} words)")
            if len(p_sentences) >= 2:
                suggestion = "Consider splitting this paragraph into 2 paragraphs around a sentence boundary where the topic shifts."
        if len(p_sentences) >= 7:
            flags.append(f"Many sentences ({len(p_sentences)})")
            suggestion = suggestion or "Consider breaking this paragraph to reduce cognitive load."
        if p_word_count < 20 and paragraph_count > 1:
            flags.append(f"Very short paragraph ({p_word_count} words)")

        para_entry = {
            "index": idx,
            "word_count": p_word_count,
            "sentence_count": len(p_sentences),
        }
        if flags:
            para_entry["flags"] = flags
        if suggestion:
            para_entry["suggestion"] = suggestion
        paragraphs.append(para_entry)

    replacement_suggestions = [
        {"from": phrase, "to": _SIMPLE_REPLACEMENTS[phrase], "count": count}
        for phrase, count in replacement_counts.items()
        if count > 0
    ]
    replacement_suggestions.sort(key=lambda x: (-x["count"], x["from"]))

    avg_words_per_sentence = (word_count / sentence_count) if sentence_count else 0.0
    avg_words_per_paragraph = (word_count / paragraph_count) if paragraph_count else 0.0
    avg_sentences_per_paragraph = (len(sentences) / paragraph_count) if paragraph_count else 0.0

    result: dict = {
        "flesch_reading_ease": round(reading_ease, 2),
        "flesch_kincaid_grade": round(grade_level, 2),
        "word_count": word_count,
        "sentence_count": len(sentences),
        "paragraph_count": paragraph_count,
        "avg_words_per_sentence": round(avg_words_per_sentence, 2),
        "avg_words_per_paragraph": round(avg_words_per_paragraph, 2),
        "avg_sentences_per_paragraph": round(avg_sentences_per_paragraph, 2),
        "paragraphs": paragraphs,
        "complex_sentences": complex_sentences,
        "replacement_suggestions": replacement_suggestions,
    }

    # Only include the fully simplified version if it changed meaningfully.
    if _normalize_whitespace(simplified_text) != _normalize_whitespace(original_text):
        result["simplified_text_preview"] = (
            simplified_text
            if len(simplified_text) <= 1200
            else simplified_text[:1197] + "..."
        )

    return result


def save_blog_post_to_file(blog_post: str, filename: str) -> dict:
    """Saves the blog post to a file."""
    with open(filename, "w") as f:
        f.write(blog_post)
    return {"status": "success"}


def analyze_codebase(directory: str) -> dict:
    """Analyzes the codebase in the given directory."""
    files = glob.glob(os.path.join(directory, "**"), recursive=True)
    codebase_context = ""
    for file in files:
        if os.path.isfile(file):
            codebase_context += f"""- **{file}**:"""
            try:
                with open(file, encoding="utf-8") as f:
                    codebase_context += f.read()
            except UnicodeDecodeError:
                with open(file, encoding="latin-1") as f:
                    codebase_context += f.read()
    return {"codebase_context": codebase_context}
