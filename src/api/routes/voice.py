"""
API routes for voice input and transcription.

The endpoints here only handle the audio→text step. Game creation routes
live under `/api/v1/{godot,bevy}/games` (or the umbrella `/api/v1/games`).
Frontend feeds the transcribed text into the standard create flow.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status

from src.api.dependencies import get_current_user
from src.api.models.user import User
from src.api.schemas.voice import TranscriptionResponse
from src.api.services.voice_service import (
    voice_service,
    NoSpeechDetectedError,
    TranscriptionTimeoutError,
    TranscriptionServiceError,
)


router = APIRouter()


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    audio_file: UploadFile = File(..., description="Audio file (WAV, MP3)"),
    current_user: User = Depends(get_current_user)
):
    """
    Transcribe audio file to text using Azure Speech

    Requires authentication. Accepts WAV or MP3 audio files.
    """
    if not voice_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription service not available"
        )

    # Validate file type
    # Different browsers use different formats: Chrome=webm, Firefox=ogg, Safari=mp4
    # Browsers may include codec params like "audio/webm;codecs=opus" so we check with startswith
    allowed_types = ["audio/wav", "audio/wave", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/aac"]
    content_type = audio_file.content_type or ""
    is_allowed = any(content_type.startswith(t) for t in allowed_types)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format. Allowed: {allowed_types}"
        )

    # Read audio data
    audio_data = await audio_file.read()

    # Debug logging
    print(f"[TRANSCRIBE] Received audio: {len(audio_data)} bytes, content_type={audio_file.content_type}, filename={audio_file.filename}")

    if len(audio_data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty"
        )

    # Warn on very small audio files (likely too short to contain speech)
    if len(audio_data) < 5000:
        print(f"[TRANSCRIBE] WARNING: Audio file is very small ({len(audio_data)} bytes) - may be too short for speech recognition")

    # Determine format - must match actual content type for ffmpeg conversion
    # Different browsers use different formats: Chrome=webm, Firefox=ogg, Safari=mp4
    # Default to webm (most common) when content_type is empty or unknown
    filename = audio_file.filename or ""

    if "wav" in content_type or filename.endswith(".wav"):
        audio_format = "wav"
    elif "ogg" in content_type or filename.endswith(".ogg"):
        audio_format = "ogg"
    elif "mp4" in content_type or "m4a" in content_type or "aac" in content_type or filename.endswith(".mp4"):
        audio_format = "mp4"
    else:
        # Default to webm - most common browser format (Chrome)
        # This handles: webm content type, .webm filename, empty content type, unknown formats
        audio_format = "webm"

    print(f"[TRANSCRIBE] Detected format: {audio_format} (content_type={content_type}, filename={filename})")

    try:
        # Transcribe
        transcript, language = await voice_service.transcribe_audio(audio_data, audio_format)

        return TranscriptionResponse(
            transcript=transcript,
            language=language,
            confidence=None  # Azure doesn't provide confidence in recognize_once
        )

    except (ValueError, NoSpeechDetectedError, TranscriptionTimeoutError) as e:
        # Client errors - user needs to provide better audio
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except TranscriptionServiceError as e:
        # Server-side errors with the transcription service
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        # Unexpected errors
        print(f"[TRANSCRIBE] Unexpected error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}"
        )
