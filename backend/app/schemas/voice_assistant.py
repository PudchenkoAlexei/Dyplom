from pydantic import BaseModel, Field


class VoiceAssistantSource(BaseModel):
    title: str
    url: str
    score: float = Field(ge=0, le=1)


class VoiceAssistantResponse(BaseModel):
    question_text: str
    answer_text: str
    confidence: float = Field(ge=0, le=1)
    source: str
    sources: list[VoiceAssistantSource] = Field(default_factory=list)
    can_create_ticket: bool
    used_llm: bool
    model_name: str | None = None


class VoiceAssistantSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
