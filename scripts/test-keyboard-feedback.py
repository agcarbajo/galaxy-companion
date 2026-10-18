#!/usr/bin/python3
"""Keep keyboard vibration gated by the setting and the active local seat."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging/galaxy-companion/usr/lib/galaxy-companion'))
from galaxy_companion.keyboard_feedback import Preferences, local_caller

user = dict(Active=True, Remote=False, Seat=('seat0', '/seat'), Type='wayland',
            Class='user', User=(1234, '/user'))
greeter = dict(user, Class='greeter', User=(99, '/greeter'))
with tempfile.TemporaryDirectory() as temporary:
    policy = Preferences(Path(temporary) / 'preferences.json')
    assert policy.duration(1234, user) == 0
    policy.set(1234, True, 2)
    assert policy.duration(1234, user) == policy.duration(99, greeter) == 42
    assert not local_caller(99, greeter), 'Greeter cannot change user preferences'
    assert policy.duration(1235, user) == 0
    assert policy.duration(1234, dict(user, Remote=True)) == 0
    assert policy.duration(1234, dict(user, Active=False)) == 0
    assert policy.duration(1234, dict(user, Seat=('seat1', '/other'))) == 0
    policy.set(1234, False, 3)
    assert policy.duration(1234, user) == policy.duration(99, greeter) == 0
    reloaded = Preferences(policy.path)
    assert reloaded.duration(99, greeter) == 0, 'Disabled stays disabled across reboot'
    policy.set(1234, True, 500)
    assert policy.duration(1234, user) == 66
print('PASS user, lock/authentication and GDM preference, disable persistence and remote/inactive UID rejection')
