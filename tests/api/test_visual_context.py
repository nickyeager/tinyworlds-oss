"""Exercise real creation/edit HTTP parsers and persistence without inference."""
import asyncio
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from src.api.core.config import get_settings
from src.api.routes import godot_games, bevy_games
from src.api.services.game_event_log import GameEventLog


def reference():
    output = io.BytesIO(); Image.new('RGB', (16, 12), 'blue').save(output, 'PNG')
    return dict(filename='paper.png', content_type='image/png', data_base64=base64.b64encode(output.getvalue()).decode())


@pytest.mark.asyncio
@pytest.mark.parametrize('purpose', ['idea', 'level', 'character', 'annotation'])
@pytest.mark.parametrize('engine,module', [('godot', godot_games), ('bevy', bevy_games)])
async def test_photo_reaches_creation_and_edit_with_private_attachment(client, auth_token, auth_user, tmp_path, monkeypatch, engine, module, purpose):
    from src.api.middleware import rate_limit
    monkeypatch.setattr(rate_limit, 'game_creation_limiter', rate_limit.RateLimiter(2, 2))
    monkeypatch.setattr(get_settings(), 'GODOT_GAMES_DIR', str(tmp_path / 'generated_games'))
    monkeypatch.setattr(module, 'get_executor', lambda _: SimpleNamespace(provider='codex'))
    captured = []
    async def capture_creation(**kw):
        captured.append(kw['request'].description)
        GameEventLog(kw['game_path']).append(dict(event_type='done', game_id=kw['game_id']))
    async def capture_edit(**kw):
        captured.append(kw['instruction'])
        kw['event_log'].append(dict(event_type='done', metadata={'game_id':kw['game_id']}))
        module._active_modifications.pop(kw['game_id'], None)
    monkeypatch.setattr(module, '_run_pipeline_to_log', capture_creation)
    monkeypatch.setattr(module, '_run_modification_to_log', capture_edit)
    headers = {'Authorization':f'Bearer {auth_token}'}
    response = await asyncio.wait_for(client.post(f'/api/v1/{engine}/games', headers=headers, json=dict(description='Use this character', reference_image={**reference(), 'purpose': purpose})), 8)
    assert response.status_code == 200, response.text
    init = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))
    game_id = init['game_id']
    assert init['description'] == 'Use this character'
    assert init['attachments'] and 'data_base64' not in response.text
    assert 'Reference image attached at:' in captured[-1]
    files = list((Path(get_settings().GODOT_GAMES_DIR) / game_id / '_user_uploads').glob('*.png'))
    assert len(files) == (2 if purpose == 'character' else 1)
    assert init['attachments'][0]['purpose'] == purpose
    # Creation stubs do not build an engine project; identify this owned fixture.
    game = files[0].parent.parent
    (game / ('project.godot' if engine == 'godot' else 'Cargo.toml')).write_text('')
    response = await asyncio.wait_for(client.post(f'/api/v1/{engine}/games/{game_id}/modify/stream', headers=headers, json=dict(instruction='Make it look like this', reference_image={**reference(), 'purpose': purpose})), 8)
    assert response.status_code == 200, response.text
    assert 'Make it look like this' in captured[-1] and 'Reference image attached at:' in captured[-1]
    if purpose == 'level': assert 'reachable goal' in captured[-1]
    if purpose == 'character': assert 'Derived transparent sprite:' in captured[-1]
    if purpose == 'annotation': assert 'colored marks' in captured[-1]
    assert len(list((game / '_user_uploads').glob('*.png'))) == (4 if purpose == 'character' else 2)
    # Raw context remains owner-private even if the game is public.
    anonymous = (await client.post('/api/v1/auth/anonymous')).json()['access_token']
    other = {'Authorization':f'Bearer {anonymous}'}
    (game / 'screenshots').mkdir(exist_ok=True)
    (game / 'screenshots' / 'level.png').write_bytes(files[0].read_bytes())
    media_url = f'/api/v1/{engine}/games/{game_id}/media'
    assert (await client.get(media_url, headers=headers)).json()['screenshots']
    assert (await client.get(media_url, headers=other)).status_code == 404
    asset_url = f'/api/v1/{engine}/games/{game_id}/assets/_user_uploads/{files[0].name}'
    assert (await client.get(asset_url, headers=headers)).status_code == 200
    assert (await client.get(asset_url, headers=other)).status_code == 404
    assert (await client.post(f'/api/v1/{engine}/games/{game_id}/modify/stream', headers=other, json=dict(instruction='edit', reference_image={**reference(), 'purpose': purpose}))).status_code == 404
