#!/usr/bin/python3
"""Synthetic cover loss, dropped events and kernel/virtual-key reconciliation."""
import os
os.environ.setdefault('GALAXY_COMPANION_DEVICE', 'gts9uwifi')
from pathlib import Path
import runpy
from unittest.mock import Mock, patch

source = Path(__file__).resolve().parents[1] / 'packaging/galaxy-companion/usr/libexec/galaxy-companion-hardware'
module = runpy.run_path(str(source))
Service = module['HardwareService']
s = Service.__new__(Service)
s.keyboard_forwarded = {30, 31}
s.keyboard_dropped = False
s.virtual_keyboard = Mock()
s.keyboard_fd = None
s._close_keyboard_reader()
assert not s.keyboard_forwarded
assert s.virtual_keyboard.emit.call_args_list[0].args == (1, 30, 0)
assert s.virtual_keyboard.emit.call_args_list[1].args == (1, 31, 0)

s.keyboard_fd = 123
s.keyboard_forwarded = {30, 31}
s.virtual_keyboard.reset_mock()
def kernel_keys(_fd, _request, keys, _mutate):
    keys[31 // 8] |= 1 << (31 % 8)
with patch.object(module['fcntl'], 'ioctl', side_effect=kernel_keys):
    s._reconcile_keyboard_keys()
assert s.keyboard_forwarded == {31}, 'Held keys must keep working normally'
assert s.virtual_keyboard.emit.call_args_list[0].args == (1, 30, 0)

pack = module['INPUT_EVENT'].pack
s.keyboard_capture = Mock()
s._mapping_for_code = lambda _code: None
s.keyboard_forwarded = {31}
s.virtual_keyboard.reset_mock()
data = b''.join(pack(0, 0, *event) for event in
    ((0, 3, 0), (1, 32, 1), (0, 0, 0), (1, 33, 1), (0, 0, 0)))
with patch.object(module['os'], 'read', return_value=data):
    s._keyboard_event(None, module['GLib'].IO_IN)
assert s.keyboard_forwarded == {33}
assert (1, 32, 1) not in [call.args for call in s.virtual_keyboard.emit.call_args_list]
print('PASS cover disconnect, stale release, held key, SYN_DROPPED and recovery; no input devices opened')
