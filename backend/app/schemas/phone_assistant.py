from pydantic import BaseModel, Field

from app.schemas.voice_assistant import VoiceAssistantSource


class PhoneAssistantResponse(BaseModel):
    call_id: str
    caller_number: str | None = None
    question_text: str
    answer_text: str
    confidence: float = Field(ge=0, le=1)
    source: str
    sources: list[VoiceAssistantSource] = Field(default_factory=list)
    used_llm: bool
    model_name: str | None = None
    answer_audio_mime_type: str
    answer_audio_base64: str


class PhoneAssistantTextResponse(BaseModel):
    call_id: str
    caller_number: str | None = None
    question_text: str
    answer_text: str
    confidence: float = Field(ge=0, le=1)
    source: str
    sources: list[VoiceAssistantSource] = Field(default_factory=list)
    used_llm: bool
    model_name: str | None = None
