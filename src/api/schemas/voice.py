"""
Pydantic schemas for voice/audio endpoints
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class TranscriptionResponse(BaseModel):
    """Response from audio transcription"""
    transcript: str = Field(..., description="Transcribed text from audio")
    language: Optional[str] = Field(None, description="Detected language")
    confidence: Optional[float] = Field(None, description="Transcription confidence 0-1")


class VoiceGameRequest(BaseModel):
    """Request to create game from voice description"""
    transcript: str = Field(..., min_length=1, description="Text transcript of game description")
    project_name: Optional[str] = Field(None, description="Optional custom project directory name")

    @field_validator('transcript')
    @classmethod
    def validate_transcript(cls, v: str) -> str:
        """Ensure transcript is not empty or whitespace only"""
        if not v or not v.strip():
            raise ValueError('Transcript cannot be empty or whitespace only')
        return v


class VoiceGameCreationResponse(BaseModel):
    """Response from creating a game from voice transcript"""
    success: bool = Field(..., description="Whether game creation succeeded")
    game_id: str = Field(..., description="UUID of created game")
    project_path: str = Field(..., description="Path to game project directory")


class TemplateFindRequest(BaseModel):
    """Request to find matching game templates"""
    description: str = Field(..., description="Natural language game description")
    max_results: int = Field(5, ge=1, le=20, description="Maximum templates to return")


class TemplateMatch(BaseModel):
    """A matched game template"""
    name: str
    github_url: str
    game_type: Optional[str] = None
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    match_reasons: List[str] = []
    godot_version: Optional[str] = None


class TemplateMatchResponse(BaseModel):
    """Response with matched templates"""
    matches: List[TemplateMatch]
    query_used: str


class VoiceToGameResponse(BaseModel):
    """Complete response from voice-to-game pipeline"""
    transcript: str = Field(..., description="Transcribed text")
    modifications: List[str] = Field([], description="Extracted modifications")
    templates: List[TemplateMatch] = Field([], description="Matched templates")
    success: bool = Field(..., description="Whether pipeline succeeded")
