from enum import StrEnum


class UserRole(StrEnum):
    student = "student"
    teacher = "teacher"
    operator = "operator"
    admin = "admin"


class TicketStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    classified = "classified"
    in_progress = "in_progress"
    waiting_user = "waiting_user"
    answered = "answered"
    closed = "closed"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class TicketEventType(StrEnum):
    created = "created"
    audio_uploaded = "audio_uploaded"
    transcribed = "transcribed"
    edited = "edited"
    submitted = "submitted"
    classified = "classified"
    claimed = "claimed"
    classification_changed = "classification_changed"
    message_sent = "message_sent"
    status_changed = "status_changed"
    closed = "closed"
