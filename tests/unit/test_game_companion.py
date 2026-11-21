"""Native player mailbox: acknowledgements, isolation, stale moves and fallback."""
import time
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from src.api.services.game_companion import Companions, GameAction, GameSync


def sync(**kwargs):
    return GameSync(client_id='a' * 32, actions=['left', 'right'], observation={'human': [1, 0], 'pip': [5, 0]}, **kwargs)


def test_move_is_queued_once_then_acknowledged_and_not_replayed():
    hub = Companions()
    state = hub.sync('owner', 'godot-demo', sync())
    joined = hub.read('owner', join=True)
    assert joined['session_id'] == state['session_id']
    assert joined['agent_connected']
    moved = hub.action('owner', state['session_id'], GameAction(action='left', expected_revision=state['revision']))
    assert moved['command']['action'] == 'left'
    assert not moved['legal_actions']
    with pytest.raises(HTTPException) as stale:
        hub.action('owner', state['session_id'], GameAction(action='left', expected_revision=state['revision']))
    assert stale.value.status_code == 409
    # Browser retries receive the same command until the game acknowledges it.
    assert hub.sync('owner', 'godot-demo', sync())['command'] == moved['command']
    ack = {'id': moved['command']['id'], 'accepted': True}
    accepted = hub.sync('owner', 'godot-demo', sync(acknowledgement=ack))
    assert accepted['command'] is None
    assert accepted['acknowledgement'] == ack
    assert accepted['legal_actions'] == ['left', 'right']
    assert hub.sync('owner', 'godot-demo', sync(acknowledgement=ack))['revision'] == accepted['revision']


def test_account_isolation_invalid_actions_and_timeouts():
    hub = Companions()
    state = hub.sync('owner', 'bevy-demo', sync())
    sid = state['session_id']
    with pytest.raises(HTTPException) as private:
        hub.read('other', sid)
    assert private.value.status_code == 404
    with pytest.raises(HTTPException) as illegal:
        hub.action('owner', sid, GameAction(action='run-code', expected_revision=state['revision']))
    assert illegal.value.status_code == 422
    hub.action('owner', sid, GameAction(action='left', expected_revision=state['revision']))
    hub.sessions[sid].lease = time.monotonic() - 1
    fallback = hub.read('owner', sid)
    assert not fallback['agent_connected'] and fallback['command'] is None
    hub.sessions[sid].updated = time.monotonic() - 21
    with pytest.raises(HTTPException):
        hub.read('owner', sid)


@pytest.mark.parametrize('change', [{'actions': ['eval()']}, {'observation': {'large': 'x' * 16001}}, {'acknowledgement': {'id': 'x', 'accepted': 'yes'}}])
def test_untrusted_game_payloads_are_bounded(change):
    values = sync().model_dump(); values.update(change)
    with pytest.raises(ValidationError):
        GameSync(**values)
