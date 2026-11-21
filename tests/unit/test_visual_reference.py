"""Camera orientation/privacy and private-context filesystem boundaries."""
import base64
import io

import pytest
from fastapi import HTTPException
from PIL import Image

from src.api.services.visual_reference import VisualReference, decode_reference, save_reference


def photo():
    image = Image.new('RGB', (24, 12), 'red')
    exif = image.getexif()
    exif[274] = 6
    exif[270] = 'private camera metadata'
    output = io.BytesIO()
    image.save(output, format='JPEG', exif=exif)
    return VisualReference(filename='paper.jpg', content_type='image/jpeg', data_base64=base64.b64encode(output.getvalue()).decode())


def test_camera_photo_rotates_and_discards_metadata(tmp_path):
    reference = photo()
    data = decode_reference(reference)
    image = Image.open(io.BytesIO(data))
    assert image.size == (12, 24)
    assert image.format == 'PNG'
    assert not image.getexif()
    assert b'private camera metadata' not in data
    path = save_reference(tmp_path, reference, data)
    assert path.parent == tmp_path / '_user_uploads'
    assert path.suffix == '.png'
    assert path.read_bytes() == data


@pytest.mark.parametrize('data', [b'not an image', b'\x89PNG\r\n\x1a\ntruncated'])
def test_rejects_disguised_and_corrupt_images(data):
    with pytest.raises(HTTPException) as error:
        decode_reference(VisualReference(content_type='image/png', data_base64=base64.b64encode(data).decode()))
    assert error.value.status_code == 400


def test_reference_cannot_follow_symlink_to_other_game(tmp_path):
    game = tmp_path / 'game'; game.mkdir()
    other = tmp_path / 'other'; other.mkdir()
    (game / '_user_uploads').symlink_to(other, target_is_directory=True)
    with pytest.raises(HTTPException):
        save_reference(game, photo(), b'private')
    assert list(other.iterdir()) == []


def character_picture():
    from PIL import ImageDraw
    image = Image.new('RGBA', (100, 100), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 20, 70, 80), fill='black')
    draw.rectangle((40, 30, 60, 50), fill='white')
    output = io.BytesIO(); image.save(output, format='PNG')
    return output.getvalue()


def test_sprite_removes_only_edge_connected_paper_and_crops():
    from src.api.services.visual_reference import extract_sprite
    image = Image.open(io.BytesIO(extract_sprite(character_picture())))
    assert image.size == (49, 69)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((14, 14)) == (255, 255, 255, 255)  # White eye stays opaque.
    assert image.getpixel((5, 5)) == (0, 0, 0, 255)


def test_blank_character_is_rejected_before_saving(tmp_path):
    output = io.BytesIO(); Image.new('RGB', (12, 12), 'white').save(output, 'PNG')
    ref = VisualReference(purpose='character', content_type='image/png', data_base64=base64.b64encode(output.getvalue()).decode())
    with pytest.raises(HTTPException, match='') as error:
        save_reference(tmp_path, ref, decode_reference(ref))
    assert error.value.status_code == 400
    assert not (tmp_path / '_user_uploads').exists()


@pytest.mark.parametrize('purpose,expected', [('level', 'reachable goal'), ('character', 'Derived transparent sprite:'), ('annotation', 'colored marks')])
def test_purpose_and_private_sprite_survive_saved_history(tmp_path, purpose, expected):
    from src.api.services.visual_reference import reference_instruction, reference_details
    from src.api.services.modification_run_log import reference_attachments
    data = character_picture()
    ref = VisualReference(purpose=purpose, content_type='image/png', data_base64=base64.b64encode(data).decode())
    path = save_reference(tmp_path, ref, decode_reference(ref))
    instruction = reference_instruction('Use this', path)
    assert expected in instruction
    assert reference_attachments(tmp_path, instruction)[0]['purpose'] == purpose
    if purpose == 'character':
        sprite = path.parent / reference_details(path)['sprite']
        assert sprite.is_file() and sprite != path
        assert Image.open(sprite).getpixel((0, 0))[3] == 0
