from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import FaqItem, IntentDefinition, IntentKeyword, Tenant
from app.services.intent_rules import IntentRules, normalize_text
from app.services.routing_engine import RoutingEngine


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 500
EXCERPT_LIMIT = 220

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-z]")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
SPACE_RE = re.compile(r"\s+")
PUNCT_EDGE_RE = re.compile(r"^[\s:;,.!?؟،؛\-–—_]+|[\s:;,.!?؟،؛\-–—_]+$")

WHATSAPP_HEADER_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm|ص|م)?)\]?\s*"
    r"(?:[-–]\s*)?(?P<sender>[^:]{1,80}):\s*(?P<message>.*)$"
)

SYSTEM_NOTICE_MARKERS = (
    "messages and calls are end-to-end encrypted",
    "message was deleted",
    "this message was deleted",
    "<media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "missed voice call",
    "الرسائل والمكالمات مشفرة",
    "تم حذف هذه الرسالة",
    "وسائط محذوفة",
    "صورة محذوفة",
)

PROTECTED_PATTERNS: list[tuple[str, str, str, tuple[str, ...], str]] = [
    ("COMPLAINT", "Complaint", "immediate_handoff", ("شكوى", "شكوي", "اشتكي", "مشكلة", "complaint", "bad service"), "Protected complaint/handoff intent."),
    ("HUMAN_REQUEST", "Human request", "immediate_handoff", ("موظف", "اكلم", "انسان", "human", "agent", "representative"), "Protected human handoff intent."),
    ("PAYMENT_TRANSFER", "Payment problem", "immediate_handoff", ("دفعت", "حولت", "تحويل", "payment", "paid", "transfer", "refund"), "Payment issue should stay review/handoff."),
    ("CERTIFICATES", "Certificate", "immediate_handoff", ("شهادة", "الشهادة", "certificate", "certificates"), "Certificate requests often require staff verification."),
]

UNIVERSAL_PATTERNS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("STEP_PREP", "STEP prep", "normal", ("اختبار ستيب", "دورة ستيب", "ستيب", "step prep", "step test", "step course", "STEP")),
    ("REGISTRATION", "Registration", "offer_handoff", ("تسجيل", "اسجل", "سجل", "registration", "register", "sign up", "enroll")),
    ("PRICING", "Pricing", "normal", ("كم السعر", "السعر", "بكم", "رسوم", "التكلفة", "اسعار", "سعر", "price", "pricing", "cost", "fees", "how much")),
    ("LOCATION", "Location", "normal", ("موقع", "وينكم", "العنوان", "location", "address", "where are you")),
    ("SCHEDULES", "Schedule", "normal", ("موعد", "مواعيد", "وقت", "دوام", "schedule", "time", "hours", "when")),
]

WEAK_KEYWORDS = {
    "كم",
    "عندكم",
    "في",
    "هل",
    "ابي",
    "أبي",
    "ابغى",
    "أبغى",
    "لو سمحت",
    "ممكن",
    "i",
    "want",
    "please",
    "do",
    "you",
    "have",
    "is",
    "the",
    "a",
}


@dataclass
class ParsedMessage:
    raw_text: str
    source_index: int
    source_type: str
    sender_hint: str | None = None
    timestamp_hint: str | None = None


class SmartImportService:
    def __init__(self):
        self.intent_rules = IntentRules()
        self.routing_engine = RoutingEngine()

    def preview_text(self, db: Session, *, tenant: Tenant, text: str, source_type: str = "paste") -> dict:
        messages = self._parse_messy_text(text, source_type=source_type)
        return self._build_preview(db, tenant=tenant, messages=messages, source_type=source_type)

    def preview_file(self, db: Session, *, tenant: Tenant, filename: str | None, content: bytes) -> dict:
        if not content:
            raise ValueError("Uploaded file is empty")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("Please keep import files under 2 MB")
        extension = self._extension(filename)
        if extension == ".csv":
            messages = self._parse_csv(content)
            source_type = "csv"
        elif extension == ".txt":
            decoded = self._decode_text(content)
            messages = self._parse_messy_text(decoded, source_type="txt")
            source_type = "txt"
        elif extension == ".xlsx":
            messages = self._parse_xlsx(content)
            source_type = "xlsx"
        else:
            raise ValueError("Unsupported import file type")
        return self._build_preview(db, tenant=tenant, messages=messages, source_type=source_type)

    def _build_preview(self, db: Session, *, tenant: Tenant, messages: list[ParsedMessage], source_type: str) -> dict:
        rows = []
        seen: dict[str, int] = {}
        total_rows = len(messages)
        duplicates = 0

        for message in messages[:MAX_IMPORT_ROWS]:
            raw_text = self._clean_message_text(message.raw_text)
            if not raw_text:
                continue
            normalized_for_hash = normalize_text(raw_text)
            if not normalized_for_hash:
                continue
            text_hash = hashlib.sha256(normalized_for_hash.encode("utf-8")).hexdigest()
            duplicate_of = seen.get(text_hash)
            if duplicate_of is not None:
                duplicates += 1
                continue
            seen[text_hash] = message.source_index

            suggestion = self._suggest_for_message(db, tenant=tenant, raw_text=raw_text)
            redacted_excerpt = self._excerpt(self.redact_pii(raw_text))
            rows.append(
                {
                    "row_id": f"row_{len(rows) + 1}",
                    "source_index": message.source_index,
                    "source_type": message.source_type,
                    "redacted_excerpt": redacted_excerpt,
                    "normalized_text": self._excerpt(self.redact_pii(normalized_for_hash), EXCERPT_LIMIT),
                    "detected_language": self.detect_language(raw_text),
                    "suggested_intent": suggestion["suggested_intent"],
                    "confidence": suggestion["confidence"],
                    "suggested_keywords": suggestion["suggested_keywords"],
                    "suggested_faq_topic": suggestion["suggested_faq_topic"],
                    "routing_hint": suggestion["routing_hint"],
                    "warnings": suggestion["warnings"],
                    "decision": "pending",
                    "editable": {
                        "training_example_text": redacted_excerpt,
                        "intent_code": suggestion["suggested_intent"]["code"],
                        "keyword_phrases": suggestion["suggested_keywords"],
                        "faq_topic_key": suggestion["suggested_faq_topic"]["topic_key"] if suggestion["suggested_faq_topic"] else "",
                        "faq_question": redacted_excerpt,
                        "faq_answer": "",
                        "routing_behavior": suggestion["routing_hint"]["behavior"],
                        "create_intent": False,
                        "create_faq": False,
                    },
                }
            )

        return {
            "source_type": source_type,
            "total_rows": total_rows,
            "previewed_rows": len(rows),
            "duplicate_rows": duplicates,
            "max_rows": MAX_IMPORT_ROWS,
            "rows": rows,
            "notes": [
                "Preview is capped and redacted.",
                "Nothing is saved until an admin approves selected rows.",
            ],
        }

    def _suggest_for_message(self, db: Session, *, tenant: Tenant, raw_text: str) -> dict:
        normalized = normalize_text(raw_text)
        language = self.detect_language(raw_text)
        warnings: list[str] = []
        if self._contains_pii(raw_text):
            warnings.append("pii_redacted")

        protected = self._match_patterns(normalized, PROTECTED_PATTERNS)
        if protected:
            code, label, route_behavior, matched, reason = protected
            confidence = 0.96
            warnings.append("protected_handoff_intent")
            intent = self._intent_payload(db, tenant.id, code, label)
            routing_hint = {"behavior": route_behavior, "owner_role": "OPERATIONS_STAFF", "reason": reason}
            keywords = self._keyword_suggestions(raw_text, matched, language)
            return {
                "suggested_intent": intent,
                "confidence": confidence,
                "suggested_keywords": keywords,
                "suggested_faq_topic": self._faq_suggestion(db, tenant.id, code, raw_text, confidence),
                "routing_hint": routing_hint,
                "warnings": warnings,
            }

        step_match = self._match_patterns(normalized, [UNIVERSAL_PATTERNS[0]])
        if step_match:
            code, label, route_behavior, matched = step_match
            confidence = 0.9
            intent = self._intent_payload(db, tenant.id, code, label)
            if not intent["existing"]:
                warnings.append("new_intent_candidate")
            return {
                "suggested_intent": intent,
                "confidence": confidence,
                "suggested_keywords": self._keyword_suggestions(raw_text, matched, language),
                "suggested_faq_topic": self._faq_suggestion(db, tenant.id, code, raw_text, confidence),
                "routing_hint": {"behavior": route_behavior, "owner_role": "BOT", "reason": "Matched STEP preparation phrase."},
                "warnings": warnings,
            }

        if self._only_weak_terms(normalized):
            warnings.append("needs_review")
            return {
                "suggested_intent": {"code": "UNKNOWN", "label": "Unknown", "existing": False},
                "confidence": 0.0,
                "suggested_keywords": [],
                "suggested_faq_topic": None,
                "routing_hint": {"behavior": "clarify", "owner_role": "OPERATIONS_STAFF", "reason": "Only weak generic terms were found."},
                "warnings": warnings,
            }

        rule_result = self.intent_rules.classify(db, tenant.id, raw_text, language_hint=self._language_hint(language))
        if rule_result.intent_code != "UNKNOWN" and rule_result.confidence >= 0.67:
            intent = self._intent_payload(db, tenant.id, rule_result.intent_code, rule_result.intent_code.replace("_", " ").title())
            route = self.routing_engine.decide(db, tenant.id, rule_result.intent_code)
            if rule_result.confidence < 0.8:
                warnings.append("needs_review")
            return {
                "suggested_intent": intent,
                "confidence": round(float(rule_result.confidence), 2),
                "suggested_keywords": self._keyword_suggestions(raw_text, tuple(rule_result.matched_phrases), language),
                "suggested_faq_topic": self._faq_suggestion(db, tenant.id, rule_result.intent_code, raw_text, rule_result.confidence),
                "routing_hint": {
                    "behavior": route.response_behavior,
                    "owner_role": route.owner_role,
                    "reason": rule_result.reasoning_short or "Matched current tenant rules.",
                },
                "warnings": warnings,
            }

        universal = self._match_patterns(normalized, UNIVERSAL_PATTERNS)
        if universal:
            code, label, route_behavior, matched = universal
            confidence = 0.82
            intent = self._intent_payload(db, tenant.id, code, label)
            if not intent["existing"]:
                warnings.append("new_intent_candidate")
            return {
                "suggested_intent": intent,
                "confidence": confidence,
                "suggested_keywords": self._keyword_suggestions(raw_text, matched, language),
                "suggested_faq_topic": self._faq_suggestion(db, tenant.id, code, raw_text, confidence),
                "routing_hint": {"behavior": route_behavior, "owner_role": "BOT" if route_behavior == "normal" else "OPERATIONS_STAFF", "reason": "Matched built-in deterministic phrase."},
                "warnings": warnings,
            }

        warnings.append("needs_review")
        return {
            "suggested_intent": {"code": "UNKNOWN", "label": "Unknown", "existing": False},
            "confidence": 0.0,
            "suggested_keywords": self._keyword_suggestions(raw_text, (), language),
            "suggested_faq_topic": None,
            "routing_hint": {"behavior": "clarify", "owner_role": "OPERATIONS_STAFF", "reason": "No confident deterministic match."},
            "warnings": warnings,
        }

    def _faq_suggestion(self, db: Session, tenant_id: int, intent_code: str, raw_text: str, confidence: float) -> dict | None:
        code = intent_code.strip().upper()
        intent = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.code == code).first()
        topic_key = (intent.default_response_topic_key if intent else None) or code.lower()
        faq = (
            db.query(FaqItem)
            .filter(FaqItem.tenant_id == tenant_id, FaqItem.topic_key == topic_key, FaqItem.status == "active")
            .order_by(FaqItem.id.desc())
            .first()
        )
        return {
            "topic_key": topic_key,
            "question": self._excerpt(self.redact_pii(raw_text), 140),
            "answer": "Existing FAQ answer" if faq else "Needs official answer",
            "existing": bool(faq),
            "confidence": round(float(confidence), 2),
        }

    def _intent_payload(self, db: Session, tenant_id: int, code: str, fallback_label: str) -> dict:
        normalized_code = self._normalize_intent_code(code)
        row = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.code == normalized_code).first()
        return {
            "code": normalized_code,
            "label": row.label if row else fallback_label,
            "existing": bool(row),
        }

    def _keyword_suggestions(self, raw_text: str, matched: tuple[str, ...], language: str) -> list[str]:
        values: list[str] = []
        for phrase in matched:
            cleaned = PUNCT_EDGE_RE.sub("", self.redact_pii(phrase)).strip()
            if self._useful_keyword(cleaned) and cleaned.lower() not in {item.lower() for item in values}:
                values.append(cleaned[:80])
        if values:
            return values[:4]
        redacted = self.redact_pii(raw_text)
        tokens = normalize_text(redacted).split()
        meaningful_tokens = [token for token in tokens if self._useful_keyword(token)]
        for size in (3, 2, 1):
            if len(meaningful_tokens) < size:
                continue
            for index in range(0, len(meaningful_tokens) - size + 1):
                candidate = " ".join(meaningful_tokens[index:index + size])
                if self._useful_keyword(candidate) and candidate.lower() not in {item.lower() for item in values}:
                    values.append(candidate[:80])
                if len(values) >= 3:
                    break
            if values:
                break
        return values[:3]

    def _match_patterns(self, normalized: str, patterns: list[tuple]) -> tuple | None:
        for row in patterns:
            phrases = row[3]
            for phrase in phrases:
                if self._phrase_matches(normalized, phrase):
                    return (*row[:3], (phrase,), *row[4:]) if len(row) == 5 else (*row[:3], (phrase,))
        return None

    def _phrase_matches(self, normalized: str, phrase: str) -> bool:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            return False
        if " " not in normalized_phrase:
            return normalized_phrase in set(normalized.split())
        return f" {normalized_phrase} " in f" {normalized} "

    def _useful_keyword(self, value: str) -> bool:
        cleaned = PUNCT_EDGE_RE.sub("", str(value or "")).strip()
        if not cleaned or cleaned.startswith("["):
            return False
        normalized = normalize_text(cleaned)
        if not normalized or normalized in {normalize_text(item) for item in WEAK_KEYWORDS}:
            return False
        if len(normalized) < 3:
            return False
        return True

    def _only_weak_terms(self, normalized: str) -> bool:
        tokens = normalized.split()
        if not tokens:
            return False
        weak = {normalize_text(item) for item in WEAK_KEYWORDS}
        return all(token in weak for token in tokens)

    def _parse_messy_text(self, text: str, *, source_type: str) -> list[ParsedMessage]:
        messages: list[ParsedMessage] = []
        current: dict[str, Any] | None = None
        for line_number, raw_line in enumerate((text or "").splitlines(), start=1):
            line = raw_line.strip("\ufeff").rstrip()
            if not line.strip():
                continue
            match = WHATSAPP_HEADER_RE.match(line.strip())
            if match:
                if current:
                    self._append_current(messages, current)
                current = {
                    "raw_text": match.group("message"),
                    "source_index": line_number,
                    "source_type": source_type,
                    "sender_hint": match.group("sender").strip(),
                    "timestamp_hint": f"{match.group('date')} {match.group('time')}",
                }
                continue
            if current:
                if current.get("timestamp_hint"):
                    current["raw_text"] = f"{current['raw_text']}\n{line.strip()}"
                else:
                    self._append_current(messages, current)
                    current = {"raw_text": line.strip(), "source_index": line_number, "source_type": source_type}
            else:
                current = {"raw_text": line.strip(), "source_index": line_number, "source_type": source_type}
        if current:
            self._append_current(messages, current)
        if not messages and text.strip():
            messages = [ParsedMessage(raw_text=text.strip(), source_index=1, source_type=source_type)]
        return messages[:MAX_IMPORT_ROWS]

    def _append_current(self, messages: list[ParsedMessage], current: dict[str, Any]) -> None:
        text = self._clean_message_text(str(current.get("raw_text") or ""))
        if not text or self._is_system_notice(text):
            return
        messages.append(
            ParsedMessage(
                raw_text=text,
                source_index=int(current.get("source_index") or len(messages) + 1),
                source_type=str(current.get("source_type") or "paste"),
                sender_hint=current.get("sender_hint"),
                timestamp_hint=current.get("timestamp_hint"),
            )
        )

    def _parse_csv(self, content: bytes) -> list[ParsedMessage]:
        decoded = self._decode_text(content)
        rows = csv.reader(io.StringIO(decoded))
        messages: list[ParsedMessage] = []
        for index, row in enumerate(rows, start=1):
            cells = [str(cell).strip() for cell in row if str(cell).strip()]
            if not cells:
                continue
            if index == 1 and any(cell.lower() in {"message", "text", "customer_message"} for cell in cells):
                continue
            text = cells[0] if len(cells) == 1 else " ".join(cells)
            if not self._is_system_notice(text):
                messages.append(ParsedMessage(raw_text=text, source_index=index, source_type="csv"))
            if len(messages) >= MAX_IMPORT_ROWS:
                break
        return messages

    def _parse_xlsx(self, content: bytes) -> list[ParsedMessage]:
        try:
            from openpyxl import load_workbook  # type: ignore
        except ImportError as exc:
            raise ValueError("XLSX import requires openpyxl to be installed") from exc
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        messages: list[ParsedMessage] = []
        for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            if not cells:
                continue
            if index == 1 and any(cell.lower() in {"message", "text", "customer_message"} for cell in cells):
                continue
            messages.append(ParsedMessage(raw_text=cells[0] if len(cells) == 1 else " ".join(cells), source_index=index, source_type="xlsx"))
            if len(messages) >= MAX_IMPORT_ROWS:
                break
        workbook.close()
        return messages

    def _decode_text(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _clean_message_text(self, value: str) -> str:
        cleaned = value.replace("\x00", " ")
        cleaned = SPACE_RE.sub(" ", cleaned).strip()
        return cleaned

    def _is_system_notice(self, value: str) -> bool:
        lowered = value.strip().lower()
        return any(marker in lowered for marker in SYSTEM_NOTICE_MARKERS)

    def _extension(self, filename: str | None) -> str:
        value = (filename or "").lower().strip()
        if "." not in value:
            return ""
        return "." + value.rsplit(".", 1)[-1]

    def redact_pii(self, value: str) -> str:
        redacted = EMAIL_RE.sub("[email]", value or "")
        redacted = URL_RE.sub("[url]", redacted)
        redacted = PHONE_RE.sub("[phone]", redacted)
        return SPACE_RE.sub(" ", redacted).strip()

    def _contains_pii(self, value: str) -> bool:
        return bool(EMAIL_RE.search(value or "") or URL_RE.search(value or "") or PHONE_RE.search(value or ""))

    def _excerpt(self, value: str, limit: int = EXCERPT_LIMIT) -> str:
        cleaned = self._clean_message_text(value)
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "…"

    def detect_language(self, value: str) -> str:
        has_ar = bool(ARABIC_RE.search(value or ""))
        has_en = bool(LATIN_RE.search(value or ""))
        if has_ar and has_en:
            return "mixed"
        if has_ar:
            return "ar"
        if has_en:
            return "en"
        return "unknown"

    def _language_hint(self, detected: str) -> str | None:
        if detected in {"ar", "en"}:
            return detected
        return None

    def _normalize_intent_code(self, value: str) -> str:
        return value.strip().upper().replace(" ", "_").replace("-", "_")
