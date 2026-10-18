# SPDX-License-Identifier: MIT
"""Shared keyboard-feedback preference for the user Shell and GDM."""
import json
import os
from pathlib import Path


def local_caller(uid, props, greeter=False):
    return (props.get('Active') and not props.get('Remote', True)
            and props.get('Seat', ('',))[0] == 'seat0'
            and props.get('Type') in ('wayland', 'x11')
            and props.get('Class') in (('user', 'greeter') if greeter else ('user',))
            and props.get('User', (-1,))[0] == uid)


class Preferences:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.values = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.values = {'enabled': False, 'strength': 2, 'uid': -1}

    def set(self, uid, enabled, strength):
        values = {'uid': uid, 'enabled': bool(enabled), 'strength': max(1, min(3, int(strength)))}
        if values == self.values:
            return
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.path.with_suffix('.new')
        temporary.write_text(json.dumps(values) + '\n')
        temporary.chmod(0o600)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        self.values = values

    def duration(self, uid, props):
        if not local_caller(uid, props, greeter=True) or not self.values.get('enabled'):
            return 0
        if props.get('Class') == 'user' and self.values.get('uid') != uid:
            return 0
        return (24, 42, 66)[max(1, min(3, int(self.values.get('strength', 2)))) - 1]
