from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.entities import FaqItem, IntentDefinition, IntentKeyword, TrainingExample


ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
PUNCTUATION_RE = re.compile(r"[\-_/\\|,.;:!?؟،؛()\[\]{}\"'`~@#$%^&*+=<>]+")
SPACE_RE = re.compile(r"\s+")
REPEATED_CHAR_RE = re.compile(r"(.)\1{2,}")
ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

BASE_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
    }
)
LOOSE_TRANSLATION = str.maketrans(
    {
        "ى": "ي",
        "ة": "ه",
    }
)
ENGLISH_CHAT_ALIASES = {
    "r": "are",
    "u": "you",
    "ur": "your",
    "pls": "please",
    "plz": "please",
    "thx": "thanks",
}
# Phrases that clearly ask for a person. They hand the conversation to staff in every
# workspace, even one that has no "human request" topic. Broader words that could
# also be part of an ordinary question (e.g. "customer service hours") are only
# hints for the HUMAN_REQUEST topic below.
PERSON_REQUEST_PHRASES: dict[str, tuple[str, ...]] = {
    "ar": (
        "اكلم موظف", "ابغى موظف", "ابغي موظف", "ابي موظف",
        "اكلم شخص", "اكلم احد", "اكلم انسان", "ابغى انسان", "ابغي انسان", "ابي انسان",
        "شخص حقيقي", "انسان حقيقي", "اكلم المسؤول", "اكلم المدير", "اكلم خدمة العملاء",
    ),
    "en": (
        "human", "representative", "real person",
        "talk to a person", "speak to a person", "speak with a person", "want a person", "need a person",
        "talk to someone", "speak to someone", "speak with someone", "talk to staff", "speak to staff",
        "live agent", "real agent", "talk to an agent", "speak to an agent", "speak with an agent",
        "talk to a manager", "speak to a manager", "talk to the manager", "speak to the manager",
    ),
}
INTENT_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "PRICING": {
        "ar": ("بكم", "كم السعر", "كم الاسعار", "اسعار", "سعر", "تكلفه", "تكلفة", "رسوم"),
        "en": ("price", "pricing", "cost", "costs", "fees", "how much", "how much is it"),
    },
    "LOCATION": {
        "ar": ("وين موقعكم", "وينكم", "موقعكم", "الموقع", "العنوان"),
        "en": ("location", "address", "where are you", "where are you located", "where r u located"),
    },
    "COMPLAINT": {
        "ar": ("شكوى", "شكوي", "عندي شكوى", "عندي شكوي", "ابي اشتكي", "ابغى اشتكي"),
        "en": ("complaint", "i want to complain"),
    },
    "HUMAN_REQUEST": {
        "ar": PERSON_REQUEST_PHRASES["ar"] + ("موظف", "خدمة العملاء", "المسؤول", "المدير"),
        "en": PERSON_REQUEST_PHRASES["en"] + ("agent", "customer service", "staff member", "employee", "operator", "manager"),
    },
    "GREETING": {
        "ar": ("السلام عليكم", "مرحبا", "اهلا", "هلا"),
        "en": ("hello", "hi", "hey"),
    },
}
EXACT_STAGE_SCORES = {
    "keyword": 0.99,
    "faq": 0.94,
    "training_example": 0.94,
    "intent_meta": 0.78,
    "intent_hint": 0.88,
}
NORMALIZED_STAGE_SCORES = {
    "keyword": 0.93,
    "faq": 0.89,
    "training_example": 0.89,
    "intent_meta": 0.74,
    "intent_hint": 0.84,
}
FUZZY_STAGE_BASE_SCORES = {
    "keyword": 0.74,
    "faq": 0.72,
    "training_example": 0.72,
    "intent_meta": 0.64,
    "intent_hint": 0.7,
}


@dataclass
class IntentResult:
    intent_code: str
    confidence: float
    matched_phrases: list[str]
    mixed: bool = False
    source: str = "rules"
    faq_topic_key: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    reasoning_short: str | None = None


@dataclass(frozen=True)
class MatchCandidate:
    intent_code: str
    phrase: str
    normalized_phrase: str
    loose_phrase: str
    token_count: int
    source_kind: str
    lang: str | None
    weight: float


@dataclass
class MatchEvidence:
    intent_code: str
    phrase: str
    source_kind: str
    stage: str
    score: float


def normalize_text(text: str) -> str:
    return _normalize(text, loose=False)


def loose_normalize_text(text: str) -> str:
    return _normalize(text, loose=True)


def _normalize(text: str, *, loose: bool) -> str:
    value = (text or "").strip().lower()
    value = ARABIC_DIACRITICS_RE.sub("", value)
    value = value.translate(BASE_TRANSLATION)
    value = PUNCTUATION_RE.sub(" ", value)
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    value = SPACE_RE.sub(" ", value).strip()
    if not value:
        return ""
    tokens = [ENGLISH_CHAT_ALIASES.get(token, token) for token in value.split()]
    value = " ".join(tokens)
    if loose:
        value = value.translate(LOOSE_TRANSLATION)
        value = REPEATED_CHAR_RE.sub(r"\1\1", value)
        value = SPACE_RE.sub(" ", value).strip()
    return value


_LOOSE_PERSON_REQUEST_PHRASES = tuple(
    loose_normalize_text(phrase) for phrases in PERSON_REQUEST_PHRASES.values() for phrase in phrases
)


def asks_for_a_person(text: str) -> bool:
    """True when the message clearly asks to talk to a person (whole words, any workspace)."""
    padded = f" {loose_normalize_text(text)} "
    return any(f" {phrase} " in padded for phrase in _LOOSE_PERSON_REQUEST_PHRASES if phrase)


def _contains_arabic(text: str) -> bool:
    return bool(ARABIC_CHAR_RE.search(text or ""))


def _infer_language(text: str) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    return "ar" if _contains_arabic(normalized) else "en"


class IntentRules:
    CLARIFICATION_FLOOR = 0.67
    OLLAMA_TRIGGER_FLOOR = 0.8
    STRONG_CONFIDENCE = 0.8
    AMBIGUITY_MARGIN = 0.08
    RISKY_INTENTS = {"COMPLAINT", "HUMAN_REQUEST"}

    def classify(self, db: Session, tenant_id: int, text: str, language_hint: str | None = None) -> IntentResult:
        normalized = normalize_text(text)
        loose_normalized = loose_normalize_text(text)
        if not normalized:
            return self._unknown("No text to classify.")

        candidates = self._load_candidates(db, tenant_id=tenant_id)
        if not candidates:
            return self._unknown("No enabled intents configured for this tenant.")

        matches = self._collect_matches(
            text=text,
            normalized=normalized,
            loose_normalized=loose_normalized,
            candidates=candidates,
            language_hint=language_hint,
        )
        if not matches:
            return self._unknown("No exact, normalized, or fuzzy rule match found.")

        ranked = self._rank_intents(matches)
        best_score, best, best_phrases = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        confidence = min(
            0.99,
            best.score
            + (0.06 if len(best_phrases) >= 2 else 0.0)
            + (0.03 if len(best_phrases) >= 3 else 0.0),
        )
        mixed = second_score > 0 and (best_score - second_score) <= self.AMBIGUITY_MARGIN

        needs_clarification = confidence < self.CLARIFICATION_FLOOR or mixed
        if best.intent_code in self.RISKY_INTENTS and confidence < self.STRONG_CONFIDENCE:
            needs_clarification = True

        source = "rules"
        reasoning = f"{best.stage} {best.source_kind} match: {best.phrase}"
        if confidence < self.OLLAMA_TRIGGER_FLOOR and best.stage == "fuzzy":
            reasoning = f"Weak {reasoning}"

        return IntentResult(
            intent_code=best.intent_code,
            confidence=confidence,
            matched_phrases=best_phrases,
            mixed=mixed,
            source=source,
            needs_clarification=needs_clarification,
            clarification_question=None,
            reasoning_short=reasoning,
        )

    def _unknown(self, reason: str) -> IntentResult:
        return IntentResult(
            intent_code="UNKNOWN",
            confidence=0.0,
            matched_phrases=[],
            mixed=False,
            source="rules",
            needs_clarification=True,
            clarification_question=None,
            reasoning_short=reason,
        )

    def _load_candidates(self, db: Session, *, tenant_id: int) -> list[MatchCandidate]:
        intents = (
            db.query(IntentDefinition)
            .filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.enabled.is_(True))
            .order_by(IntentDefinition.code)
            .all()
        )
        if not intents:
            return []

        allowed_intents = {row.code for row in intents}
        intent_by_topic = {row.default_response_topic_key: row.code for row in intents if row.default_response_topic_key}
        keywords = (
            db.query(IntentKeyword)
            .filter(IntentKeyword.tenant_id == tenant_id, IntentKeyword.intent_code.in_(allowed_intents))
            .order_by(IntentKeyword.intent_code, IntentKeyword.id)
            .all()
        )
        faqs = (
            db.query(FaqItem)
            .filter(FaqItem.tenant_id == tenant_id, FaqItem.status == "active")
            .order_by(FaqItem.topic_key, FaqItem.id)
            .all()
        )
        examples = (
            db.query(TrainingExample)
            .filter(TrainingExample.tenant_id == tenant_id, TrainingExample.labeled_intent.in_(allowed_intents))
            .order_by(TrainingExample.id.desc())
            .limit(100)
            .all()
        )

        candidates: list[MatchCandidate] = []
        seen: set[tuple[str, str, str]] = set()

        def add_candidate(intent_code: str, phrase: str | None, source_kind: str, *, lang: str | None, weight: float) -> None:
            value = (phrase or "").strip()
            normalized_phrase = normalize_text(value)
            loose_phrase = loose_normalize_text(value)
            if not normalized_phrase:
                return
            signature = (intent_code, normalized_phrase, source_kind)
            if signature in seen:
                return
            seen.add(signature)
            candidates.append(
                MatchCandidate(
                    intent_code=intent_code,
                    phrase=value,
                    normalized_phrase=normalized_phrase,
                    loose_phrase=loose_phrase,
                    token_count=len(normalized_phrase.split()),
                    source_kind=source_kind,
                    lang=lang,
                    weight=weight,
                )
            )

        for row in keywords:
            add_candidate(row.intent_code, row.phrase, "keyword", lang=(row.lang or "").strip().lower() or None, weight=max(float(row.weight or 1), 1.0))

        for row in intents:
            add_candidate(row.code, row.label, "intent_meta", lang=None, weight=1.0)
            add_candidate(row.code, row.code.replace("_", " "), "intent_meta", lang=None, weight=1.0)
            add_candidate(row.code, row.default_response_topic_key, "intent_meta", lang=None, weight=1.0)
            for lang, phrase in self._hint_phrases(row):
                add_candidate(row.code, phrase, "intent_hint", lang=lang, weight=1.0)

        for row in faqs:
            intent_code = intent_by_topic.get(row.topic_key)
            if not intent_code:
                continue
            add_candidate(intent_code, row.question_ar, "faq", lang="ar", weight=1.0)
            add_candidate(intent_code, row.english_question, "faq", lang="en", weight=1.0)

        for row in examples:
            add_candidate(row.labeled_intent or "", row.raw_text, "training_example", lang=_infer_language(row.raw_text), weight=1.0)
            add_candidate(row.labeled_intent or "", row.normalized_text, "training_example", lang=_infer_language(row.normalized_text), weight=1.0)

        return candidates

    def _hint_phrases(self, intent: IntentDefinition) -> list[tuple[str, str]]:
        keys = {
            normalize_text(intent.code.replace("_", " ")),
            normalize_text(intent.label),
            normalize_text(intent.default_response_topic_key or ""),
        }
        results: list[tuple[str, str]] = []
        for canonical, phrases in INTENT_HINTS.items():
            canonical_key = normalize_text(canonical.replace("_", " "))
            if canonical_key not in keys:
                continue
            for lang, values in phrases.items():
                for phrase in values:
                    results.append((lang, phrase))
        return results

    def _collect_matches(
        self,
        *,
        text: str,
        normalized: str,
        loose_normalized: str,
        candidates: list[MatchCandidate],
        language_hint: str | None,
    ) -> list[MatchEvidence]:
        raw_lower = (text or "").lower()
        matches: list[MatchEvidence] = []

        for candidate in candidates:
            if language_hint and candidate.lang and candidate.lang != language_hint:
                if not self._allow_cross_language_match(candidate, normalized):
                    continue

            evidence = self._match_candidate(
                candidate,
                raw_lower=raw_lower,
                normalized=normalized,
                loose_normalized=loose_normalized,
            )
            if evidence is None:
                continue
            matches.append(evidence)

        return matches

    def _rank_intents(self, matches: list[MatchEvidence]) -> list[tuple[float, MatchEvidence, list[str]]]:
        grouped: dict[str, list[MatchEvidence]] = {}
        for evidence in matches:
            grouped.setdefault(evidence.intent_code, []).append(evidence)

        ranked: list[tuple[float, MatchEvidence, list[str]]] = []
        for intent_code, evidences in grouped.items():
            evidences.sort(key=lambda row: row.score, reverse=True)
            ranking_score = 0.0
            for index, evidence in enumerate(evidences[:3]):
                weight = 1.0 if index == 0 else (0.45 if index == 1 else 0.25)
                ranking_score += evidence.score * weight
            phrases = list(dict.fromkeys(row.phrase for row in evidences[:3]))
            ranked.append((ranking_score, evidences[0], phrases))

        ranked.sort(key=lambda row: row[0], reverse=True)
        return ranked

    def _allow_cross_language_match(self, candidate: MatchCandidate, normalized: str) -> bool:
        if candidate.source_kind == "intent_hint":
            return candidate.normalized_phrase in normalized
        return False

    def _match_candidate(
        self,
        candidate: MatchCandidate,
        *,
        raw_lower: str,
        normalized: str,
        loose_normalized: str,
    ) -> MatchEvidence | None:
        raw_phrase_lower = candidate.phrase.lower().strip()
        if raw_phrase_lower and self._contains_phrase(SPACE_RE.sub(" ", raw_lower).strip(), raw_phrase_lower):
            return MatchEvidence(
                intent_code=candidate.intent_code,
                phrase=candidate.phrase,
                source_kind=candidate.source_kind,
                stage="exact",
                score=self._score_for_stage(candidate, "exact", 1.0),
            )

        if self._contains_phrase(normalized, candidate.normalized_phrase):
            return MatchEvidence(
                intent_code=candidate.intent_code,
                phrase=candidate.phrase,
                source_kind=candidate.source_kind,
                stage="normalized",
                score=self._score_for_stage(candidate, "normalized", 1.0),
            )

        similarity = self._best_fuzzy_similarity(loose_normalized, candidate.loose_phrase, token_count=candidate.token_count)
        threshold = self._fuzzy_threshold(candidate)
        if similarity >= threshold:
            return MatchEvidence(
                intent_code=candidate.intent_code,
                phrase=candidate.phrase,
                source_kind=candidate.source_kind,
                stage="fuzzy",
                score=self._score_for_stage(candidate, "fuzzy", similarity),
            )

        return None

    def _contains_phrase(self, haystack: str, needle: str) -> bool:
        if not haystack or not needle:
            return False
        return f" {needle} " in f" {haystack} "

    def _score_for_stage(self, candidate: MatchCandidate, stage: str, similarity: float) -> float:
        if stage == "exact":
            base = EXACT_STAGE_SCORES[candidate.source_kind]
        elif stage == "normalized":
            base = NORMALIZED_STAGE_SCORES[candidate.source_kind]
        else:
            base = FUZZY_STAGE_BASE_SCORES[candidate.source_kind]
        weighted = base + min(max(candidate.weight - 1.0, 0.0), 5.0) * 0.015
        if stage == "fuzzy":
            weighted += max(0.0, similarity - 0.75) * 0.35
        return min(0.99, weighted)

    def _fuzzy_threshold(self, candidate: MatchCandidate) -> float:
        if candidate.token_count <= 1:
            return 0.74 if len(candidate.loose_phrase) <= 5 else 0.78
        if candidate.source_kind == "intent_hint":
            return 0.84
        return 0.8

    def _best_fuzzy_similarity(self, message: str, phrase: str, *, token_count: int) -> float:
        if not message or not phrase:
            return 0.0
        if message == phrase:
            return 1.0

        message_tokens = message.split()
        phrase_tokens = phrase.split()
        if not message_tokens or not phrase_tokens:
            return 0.0

        best = 0.0
        if len(phrase_tokens) == 1:
            for token in message_tokens:
                best = max(best, SequenceMatcher(None, token, phrase).ratio())
            return best

        min_window = max(1, token_count - 1)
        max_window = min(len(message_tokens), token_count + 1)
        for window_size in range(min_window, max_window + 1):
            for start in range(0, len(message_tokens) - window_size + 1):
                chunk = " ".join(message_tokens[start : start + window_size])
                best = max(best, SequenceMatcher(None, chunk, phrase).ratio())
        return best
