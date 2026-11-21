# Test Fixtures

Shared test data and resources for the TinyWorlds test suite.

## Directory Structure

```
fixtures/
├── godot_projects/          # Sample Godot project structures
│   └── minimal_project/     # Minimal valid Godot 4.x project
│       ├── project.godot    # Project configuration
│       └── player.gd        # Sample player script
├── audio/                   # Sample audio files for voice tests
│   └── (add .wav/.webm files as needed)
└── images/                  # Sample images for asset tests
    └── (add .png files as needed)
```

## Usage

### Godot Project Fixtures

```python
import shutil
from pathlib import Path

# Copy minimal project for testing
fixtures = Path(__file__).parent / "fixtures"
minimal_project = fixtures / "godot_projects" / "minimal_project"

# Copy to temp directory for test isolation
test_project = tmp_path / "test_game"
shutil.copytree(minimal_project, test_project)
```

### Audio Fixtures

Place sample audio files in `audio/` for voice transcription tests.

Supported formats:
- `.wav` - Uncompressed audio
- `.webm` - Browser MediaRecorder format

### Image Fixtures

Place sample images in `images/` for asset processing tests.

Recommended:
- `test_sprite_64x64.png` - Small sprite for unit tests
- `test_background_512x256.png` - Background for asset tests
