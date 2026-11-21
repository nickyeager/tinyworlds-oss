"""
Integration tests for voice transcription endpoint.

Tests the /api/v1/voice/transcribe endpoint with real Azure Speech SDK calls.
Uses Azure TTS to generate test audio, then verifies transcription accuracy.
"""
import os
import tempfile
import pytest
import httpx
from pathlib import Path

pytestmark = pytest.mark.integration

# Check for required environment variables
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

API_BASE = "http://localhost:8001"


def get_auth_token() -> str:
    """Get an anonymous authentication token."""
    response = httpx.post(f"{API_BASE}/api/v1/auth/anonymous")
    response.raise_for_status()
    return response.json()["access_token"]


def synthesize_speech(text: str) -> bytes:
    """
    Use Azure TTS to generate audio from text.
    Returns WAV audio bytes.
    """
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION
    )
    speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"

    # Synthesize to memory
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=None  # Output to memory
    )

    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    else:
        raise RuntimeError(f"TTS failed: {result.reason}")


@pytest.fixture
def auth_token():
    """Fixture to get authentication token."""
    return get_auth_token()


class TestVoiceTranscription:
    """Tests for voice transcription endpoint."""

    def test_browser_style_webm_audio_returns_400_not_500(self, auth_token):
        """
        Test that browser-recorded webm audio returns 400 (not 500) when no speech detected.

        This test simulates exactly what the browser MediaRecorder produces.
        MUST return 400 with user-friendly message, NOT 500 Internal Server Error.
        """
        import subprocess

        # Create webm audio exactly like browser MediaRecorder (opus codec, short duration)
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", "0.5",  # 500ms - typical quick button press
            "-c:a", "libopus",
            "/tmp/browser_style.webm"
        ], capture_output=True)

        assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"

        with open("/tmp/browser_style.webm", "rb") as f:
            webm_data = f.read()

        # Send exactly like browser does
        files = {"audio_file": ("recording.webm", webm_data, "audio/webm")}
        headers = {"Authorization": f"Bearer {auth_token}"}

        response = httpx.post(
            f"{API_BASE}/api/v1/voice/transcribe",
            files=files,
            headers=headers,
            timeout=60.0
        )

        # CRITICAL: Must be 400 (client error), NOT 500 (server error)
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}: {response.text}"

        data = response.json()
        assert "detail" in data, f"Response missing 'detail': {data}"

        # Error message should be helpful, not "Internal Server Error"
        assert "internal" not in data["detail"].lower(), \
            f"Got internal error instead of user-friendly message: {data['detail']}"

        Path("/tmp/browser_style.webm").unlink(missing_ok=True)

    def test_transcribe_real_speech(self, auth_token):
        """
        Test transcription with real Azure Speech SDK.

        Uses Azure TTS to generate audio, then transcribes it back.
        Verifies the transcription matches the original text.
        """
        # Generate test audio using TTS
        test_text = "Hello, this is a test of voice transcription."
        audio_data = synthesize_speech(test_text)

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            audio_path = f.name

        try:
            # Send to transcription endpoint
            with open(audio_path, "rb") as f:
                files = {"audio_file": ("test.wav", f, "audio/wav")}
                headers = {"Authorization": f"Bearer {auth_token}"}

                response = httpx.post(
                    f"{API_BASE}/api/v1/voice/transcribe",
                    files=files,
                    headers=headers,
                    timeout=30.0
                )

            # Verify response
            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

            data = response.json()
            assert "transcript" in data, f"Response missing 'transcript': {data}"

            transcript = data["transcript"].lower()
            # Check key words are present (exact match not required due to TTS/STT variance)
            assert "hello" in transcript or "test" in transcript, \
                f"Transcript '{transcript}' doesn't contain expected words"

        finally:
            Path(audio_path).unlink(missing_ok=True)

    def test_transcribe_empty_audio_returns_400_with_helpful_message(self, auth_token):
        """
        Test that empty/short audio file returns 400 with helpful message.

        Should return 400 (not 500) with user-friendly guidance.
        """
        # Create empty audio file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # Write minimal WAV header but no audio data
            f.write(b"RIFF")
            f.write((36).to_bytes(4, 'little'))  # File size
            f.write(b"WAVE")
            f.write(b"fmt ")
            f.write((16).to_bytes(4, 'little'))  # Chunk size
            f.write((1).to_bytes(2, 'little'))   # Audio format (PCM)
            f.write((1).to_bytes(2, 'little'))   # Channels
            f.write((16000).to_bytes(4, 'little'))  # Sample rate
            f.write((32000).to_bytes(4, 'little'))  # Byte rate
            f.write((2).to_bytes(2, 'little'))   # Block align
            f.write((16).to_bytes(2, 'little'))  # Bits per sample
            f.write(b"data")
            f.write((0).to_bytes(4, 'little'))   # Data size (empty)
            audio_path = f.name

        try:
            with open(audio_path, "rb") as f:
                files = {"audio_file": ("test.wav", f, "audio/wav")}
                headers = {"Authorization": f"Bearer {auth_token}"}

                response = httpx.post(
                    f"{API_BASE}/api/v1/voice/transcribe",
                    files=files,
                    headers=headers,
                    timeout=60.0
                )

            # Empty audio should return 400 (client error), not 500 (server error)
            assert response.status_code == 400, \
                f"Expected 400 for empty audio, got {response.status_code}: {response.text}"

            data = response.json()
            assert "detail" in data, "Error response missing 'detail'"

            detail = data["detail"].lower()
            # Error should be user-friendly with guidance
            assert any(word in detail for word in ["speech", "short", "hold", "speak"]), \
                f"Error message should guide user: {data['detail']}"

        finally:
            Path(audio_path).unlink(missing_ok=True)

    def test_transcribe_invalid_format_rejected(self, auth_token):
        """
        Test that invalid file format is rejected with 400.
        """
        # Create a text file pretending to be audio
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"This is not audio data")
            fake_path = f.name

        try:
            with open(fake_path, "rb") as f:
                files = {"audio_file": ("test.txt", f, "text/plain")}
                headers = {"Authorization": f"Bearer {auth_token}"}

                response = httpx.post(
                    f"{API_BASE}/api/v1/voice/transcribe",
                    files=files,
                    headers=headers,
                    timeout=30.0
                )

            assert response.status_code == 400, \
                f"Expected 400 for invalid format, got {response.status_code}"

            data = response.json()
            assert "unsupported" in data["detail"].lower() or "format" in data["detail"].lower(), \
                f"Error should mention format: {data['detail']}"

        finally:
            Path(fake_path).unlink(missing_ok=True)

    def test_transcribe_unauthorized(self):
        """
        Test that missing auth token returns 401.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio")
            audio_path = f.name

        try:
            with open(audio_path, "rb") as f:
                files = {"audio_file": ("test.wav", f, "audio/wav")}

                response = httpx.post(
                    f"{API_BASE}/api/v1/voice/transcribe",
                    files=files,
                    timeout=30.0
                )

            assert response.status_code == 401, \
                f"Expected 401 without auth, got {response.status_code}"

        finally:
            Path(audio_path).unlink(missing_ok=True)


class TestVoiceServiceDirect:
    """Direct tests of VoiceService class."""

    def test_service_initialized_with_credentials(self):
        """
        Test that VoiceService initializes when Azure credentials are set.
        """
        from src.api.services.voice_service import voice_service

        assert voice_service is not None, \
            "voice_service should be initialized when Azure credentials are set"
        assert hasattr(voice_service, 'transcribe_audio'), \
            "voice_service should have transcribe_audio method"

    @pytest.mark.asyncio
    async def test_transcribe_webm_format(self):
        """
        Test transcription of webm format (common from browser MediaRecorder).
        """
        from src.api.services.voice_service import VoiceService
        import subprocess

        service = VoiceService()

        # Generate test audio using TTS
        test_text = "Testing webm format."
        wav_audio = synthesize_speech(test_text)

        # Convert WAV to WebM using ffmpeg
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_file.write(wav_audio)
            wav_path = wav_file.name

        webm_path = wav_path.replace(".wav", ".webm")

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", webm_path],
                capture_output=True,
                timeout=30
            )

            assert result.returncode == 0, \
                f"ffmpeg webm conversion failed - ensure ffmpeg with libopus is installed: {result.stderr.decode()}"

            with open(webm_path, "rb") as f:
                webm_audio = f.read()

            # Transcribe the webm audio
            transcript, language = await service.transcribe_audio(webm_audio, "webm")

            assert transcript is not None, "Transcript should not be None"
            assert len(transcript) > 0, "Transcript should not be empty"
            assert "test" in transcript.lower() or "webm" in transcript.lower(), \
                f"Transcript '{transcript}' doesn't match expected content"

        finally:
            Path(wav_path).unlink(missing_ok=True)
            Path(webm_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_transcribe_ogg_format(self):
        """
        Test transcription of ogg format (Firefox MediaRecorder default).

        Firefox uses audio/ogg;codecs=opus by default, not webm.
        This test verifies the backend correctly handles ogg audio.
        """
        from src.api.services.voice_service import VoiceService
        import subprocess

        service = VoiceService()

        # Generate test audio using TTS
        test_text = "Testing ogg format."
        wav_audio = synthesize_speech(test_text)

        # Convert WAV to OGG using ffmpeg (simulating Firefox MediaRecorder)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_file.write(wav_audio)
            wav_path = wav_file.name

        ogg_path = wav_path.replace(".wav", ".ogg")

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", ogg_path],
                capture_output=True,
                timeout=30
            )

            assert result.returncode == 0, f"ffmpeg ogg conversion failed: {result.stderr.decode()}"

            with open(ogg_path, "rb") as f:
                ogg_audio = f.read()

            # Transcribe the ogg audio
            transcript, language = await service.transcribe_audio(ogg_audio, "ogg")

            assert transcript is not None, "Transcript should not be None"
            assert len(transcript) > 0, "Transcript should not be empty"
            assert "test" in transcript.lower() or "ogg" in transcript.lower(), \
                f"Transcript '{transcript}' doesn't match expected content"

        finally:
            Path(wav_path).unlink(missing_ok=True)
            Path(ogg_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_transcribe_mp4_format(self):
        """
        Test transcription of mp4/aac format (Safari MediaRecorder default).

        Safari uses audio/mp4 or audio/aac, not webm.
        This test verifies the backend correctly handles mp4 audio.
        """
        from src.api.services.voice_service import VoiceService
        import subprocess

        service = VoiceService()

        # Generate test audio using TTS
        test_text = "Testing mp4 format."
        wav_audio = synthesize_speech(test_text)

        # Convert WAV to M4A/MP4 using ffmpeg (simulating Safari MediaRecorder)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_file.write(wav_audio)
            wav_path = wav_file.name

        mp4_path = wav_path.replace(".wav", ".mp4")

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-c:a", "aac", "-b:a", "128k", mp4_path],
                capture_output=True,
                timeout=30
            )

            assert result.returncode == 0, f"ffmpeg mp4 conversion failed: {result.stderr.decode()}"

            with open(mp4_path, "rb") as f:
                mp4_audio = f.read()

            # Transcribe the mp4 audio
            transcript, language = await service.transcribe_audio(mp4_audio, "mp4")

            assert transcript is not None, "Transcript should not be None"
            assert len(transcript) > 0, "Transcript should not be empty"
            assert "test" in transcript.lower() or "mp4" in transcript.lower(), \
                f"Transcript '{transcript}' doesn't match expected content"

        finally:
            Path(wav_path).unlink(missing_ok=True)
            Path(mp4_path).unlink(missing_ok=True)


class TestBrowserAudioFormatsEndpoint:
    """Test API endpoint with different browser audio formats."""

    def test_firefox_ogg_format(self, auth_token):
        """
        Test that Firefox's ogg/opus format is accepted and transcribed correctly.

        Firefox MediaRecorder produces audio/ogg;codecs=opus by default.
        This was previously failing because we hardcoded the blob type as webm.
        """
        import subprocess

        # Create ogg audio like Firefox MediaRecorder produces
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libopus",
            "/tmp/firefox_style.ogg"
        ], capture_output=True)

        assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"

        with open("/tmp/firefox_style.ogg", "rb") as f:
            ogg_data = f.read()

        # Send exactly like Firefox browser does
        files = {"audio_file": ("recording.ogg", ogg_data, "audio/ogg")}
        headers = {"Authorization": f"Bearer {auth_token}"}

        response = httpx.post(
            f"{API_BASE}/api/v1/voice/transcribe",
            files=files,
            headers=headers,
            timeout=60.0
        )

        # Should be 400 (no speech in sine wave) NOT 500 (format error)
        assert response.status_code == 400, \
            f"Expected 400 for ogg with no speech, got {response.status_code}: {response.text}"

        data = response.json()
        # Error should be about speech, not about format conversion
        assert "convert" not in data["detail"].lower() and "format" not in data["detail"].lower(), \
            f"Got format error instead of speech detection error: {data['detail']}"

        Path("/tmp/firefox_style.ogg").unlink(missing_ok=True)

    def test_safari_mp4_format(self, auth_token):
        """
        Test that Safari's mp4/aac format is accepted and transcribed correctly.

        Safari MediaRecorder produces audio/mp4 or audio/aac.
        This was previously failing because we only handled webm.
        """
        import subprocess

        # Create mp4 audio like Safari MediaRecorder produces
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "aac", "-b:a", "128k",
            "/tmp/safari_style.mp4"
        ], capture_output=True)

        assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"

        with open("/tmp/safari_style.mp4", "rb") as f:
            mp4_data = f.read()

        # Send exactly like Safari browser does
        files = {"audio_file": ("recording.mp4", mp4_data, "audio/mp4")}
        headers = {"Authorization": f"Bearer {auth_token}"}

        response = httpx.post(
            f"{API_BASE}/api/v1/voice/transcribe",
            files=files,
            headers=headers,
            timeout=60.0
        )

        # Should be 400 (no speech in sine wave) NOT 500 (format error)
        assert response.status_code == 400, \
            f"Expected 400 for mp4 with no speech, got {response.status_code}: {response.text}"

        data = response.json()
        # Error should be about speech, not about format conversion
        assert "convert" not in data["detail"].lower() and "format" not in data["detail"].lower(), \
            f"Got format error instead of speech detection error: {data['detail']}"

        Path("/tmp/safari_style.mp4").unlink(missing_ok=True)

    def test_chrome_webm_with_codec_params(self, auth_token):
        """
        TDD RED: Test that Chrome's webm with codec params is accepted.

        Chrome MediaRecorder sends 'audio/webm;codecs=opus' as content-type,
        NOT just 'audio/webm'. The backend currently does exact string matching
        which fails because 'audio/webm;codecs=opus' is not in the allowed list.

        This test MUST FAIL initially to prove the bug exists.
        After fixing, it should pass.

        ERROR REPRODUCED:
        "Unsupported audio format. Allowed: ['audio/wav', 'audio/wave', 'audio/x-wav',
        'audio/mpeg', 'audio/mp3', 'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/x-m4a', 'audio/aac']"
        """
        import subprocess

        # Create webm audio like Chrome MediaRecorder produces
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libopus",
            "/tmp/chrome_style.webm"
        ], capture_output=True)

        assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"

        with open("/tmp/chrome_style.webm", "rb") as f:
            webm_data = f.read()

        # Send EXACTLY like Chrome browser does - with codec params in content-type
        # This is the key difference: "audio/webm;codecs=opus" vs "audio/webm"
        files = {"audio_file": ("recording.webm", webm_data, "audio/webm;codecs=opus")}
        headers = {"Authorization": f"Bearer {auth_token}"}

        response = httpx.post(
            f"{API_BASE}/api/v1/voice/transcribe",
            files=files,
            headers=headers,
            timeout=60.0
        )

        # CRITICAL: Response should NOT be 400 with "Unsupported audio format"
        # It should be accepted and processed (returning 400 for no speech is OK)
        if response.status_code == 400:
            data = response.json()
            # This assertion FAILS if we get "Unsupported audio format" error
            # That's the bug we're proving exists
            assert "unsupported" not in data["detail"].lower(), \
                f"BUG: Content-type 'audio/webm;codecs=opus' rejected as unsupported: {data['detail']}"

        Path("/tmp/chrome_style.webm").unlink(missing_ok=True)
