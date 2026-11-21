"""
Business logic for voice transcription and processing
"""
from pathlib import Path
from typing import Optional, List, Dict, Any
import os
import tempfile
import subprocess

try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False


class TranscriptionError(Exception):
    """Base exception for transcription errors."""
    pass


class NoSpeechDetectedError(TranscriptionError):
    """Raised when no speech is detected in the audio (client error)."""
    pass


class TranscriptionTimeoutError(TranscriptionError):
    """Raised when transcription times out waiting for speech (client error)."""
    pass


class TranscriptionServiceError(TranscriptionError):
    """Raised when the transcription service fails (server error)."""
    pass


def convert_to_wav(input_path: str, output_path: str) -> tuple[bool, str]:
    """Convert audio file to WAV format using ffmpeg.

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    # Check input file exists and size
    if not os.path.exists(input_path):
        error = f"Input file does not exist: {input_path}"
        print(f"[FFMPEG ERROR] {error}")
        return False, error

    input_size = os.path.getsize(input_path)
    print(f"[FFMPEG] Converting: {input_path} ({input_size} bytes) -> {output_path}")

    if input_size == 0:
        error = "Input audio file is empty (0 bytes) - recording may have failed"
        print(f"[FFMPEG ERROR] {error}")
        return False, error

    if input_size < 100:
        print(f"[FFMPEG WARNING] Input file is very small ({input_size} bytes) - may be corrupt")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-ar", "16000",  # 16kHz sample rate for speech
                "-ac", "1",      # mono
                "-f", "wav",
                output_path
            ],
            capture_output=True,
            timeout=30
        )
        if result.returncode != 0:
            stderr = result.stderr.decode()[:500]
            print(f"[FFMPEG ERROR] returncode={result.returncode}")
            print(f"[FFMPEG STDERR] {stderr}")
            # Extract useful error info
            if "Invalid data" in stderr:
                return False, f"Audio file is corrupted or not a valid audio format"
            elif "does not contain" in stderr or "no such file" in stderr.lower():
                return False, f"Audio file format not recognized"
            else:
                return False, f"FFmpeg conversion failed: {stderr[:200]}"
        else:
            output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            print(f"[FFMPEG SUCCESS] Output: {output_path} ({output_size} bytes)")
            return True, ""
    except subprocess.TimeoutExpired:
        error = "Audio conversion timed out after 30 seconds"
        print(f"[FFMPEG ERROR] {error}")
        return False, error
    except FileNotFoundError:
        error = "FFmpeg not found - please install ffmpeg"
        print(f"[FFMPEG ERROR] {error}")
        return False, error
    except Exception as e:
        error = f"Unexpected error: {type(e).__name__}: {e}"
        print(f"[FFMPEG EXCEPTION] {error}")
        return False, error

from src.voice.modification_extractor import ModificationExtractor


class VoiceService:
    """Service for handling voice transcription"""

    def __init__(self, required: bool = False):
        """Initialize Azure Speech service and modification extractor

        Args:
            required: If True, raise errors for missing credentials.
                     If False, service will be None if credentials missing.
        """
        self.speech_key = os.getenv("AZURE_SPEECH_KEY")
        self.speech_region = os.getenv("AZURE_SPEECH_REGION")

        if not AZURE_AVAILABLE:
            if required:
                raise RuntimeError("Azure Speech SDK not installed")
            return

        if not self.speech_key or not self.speech_region:
            if required:
                raise ValueError(
                    "Azure Speech credentials required. "
                    "Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION"
                )
            return

        # Initialize modification extractor
        self.modification_extractor = ModificationExtractor()

    async def transcribe_audio(
        self,
        audio_data: bytes,
        audio_format: str = "wav"
    ) -> tuple[str, Optional[str]]:
        """
        Transcribe audio to text using Azure Speech

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format (wav, mp3, webm, etc)

        Returns:
            Tuple of (transcript, language)
        """
        # Save audio to temp file
        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        wav_path = None
        try:
            # Convert non-wav formats to wav (Azure Speech SDK needs wav)
            if audio_format != "wav":
                wav_path = tmp_path.replace(f".{audio_format}", ".wav")
                success, error_msg = convert_to_wav(tmp_path, wav_path)
                if not success:
                    raise RuntimeError(f"Failed to convert {audio_format} to wav: {error_msg}")
                audio_path = wav_path
            else:
                audio_path = tmp_path

            # Configure Azure Speech
            speech_config = speechsdk.SpeechConfig(
                subscription=self.speech_key,
                region=self.speech_region
            )

            # Create audio config from file
            audio_config = speechsdk.AudioConfig(filename=audio_path)

            # Create recognizer
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config
            )

            # Perform transcription
            result = recognizer.recognize_once()

            # Check result
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                return result.text, None  # language detection can be added
            elif result.reason == speechsdk.ResultReason.NoMatch:
                raise NoSpeechDetectedError("No speech could be recognized in the audio")
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                error_details = cancellation.error_details or ""

                # Determine if this is a client error (no speech/timeout) or server error
                if "timeout" in error_details.lower() or "no recognition result" in error_details.lower():
                    raise TranscriptionTimeoutError(
                        "Recording too short or no speech detected. Hold the button longer and speak clearly."
                    )
                elif "invalid subscription" in error_details.lower() or "authentication" in error_details.lower():
                    raise TranscriptionServiceError(f"Azure Speech service authentication failed: {error_details}")
                else:
                    # Other cancellation reasons - treat as server error
                    raise TranscriptionServiceError(f"Speech recognition failed: {cancellation.reason} - {error_details}")

        finally:
            # Clean up temp files
            Path(tmp_path).unlink(missing_ok=True)
            if wav_path:
                Path(wav_path).unlink(missing_ok=True)

    def extract_modifications(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract game modifications from natural language

        Args:
            text: Natural language description

        Returns:
            List of modification dictionaries
        """
        modifications = self.modification_extractor.extract(text)
        return self.modification_extractor.to_dict(modifications)


# Singleton instance - will be None if Azure credentials not available
def _create_voice_service() -> Optional['VoiceService']:
    """Create voice service if Azure credentials are available"""
    if not AZURE_AVAILABLE:
        return None

    speech_key = os.getenv("AZURE_SPEECH_KEY")
    speech_region = os.getenv("AZURE_SPEECH_REGION")

    if not speech_key or not speech_region:
        return None

    try:
        return VoiceService()
    except Exception:
        return None

voice_service = _create_voice_service()
