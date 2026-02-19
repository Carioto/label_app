# printer_brother_pt.py
# -*- coding: utf-8 -*-
"""
Brother TD-2120N P-touch Template backend over Bluetooth serial (no driver).
Vendored pyserial:
  <app_root>/
    printer_brother_pt.py
    vendor/pyserial/serial/__init__.py  (and the rest of pyserial)
"""

import os, sys

# Make vendored pyserial importable
VENDOR = os.path.join(os.path.dirname(__file__), "vendor", "pyserial")
if os.path.isdir(VENDOR) and VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import serial
from serial.tools import list_ports

PREFIX = b'^'  # default command prefix

def _bcat(*parts): return b''.join(parts)
def esc(*bs):
    # prefix ESC then concatenate all byte strings
    return b'\x1b' + b''.join(bs)


# ---- P-touch Template commands (dynamic, non-persistent) ----
def cmd_mode_template():           # ESC i a 03h  -> P-touch Template mode (session)
    return esc(b'i', b'a', b'\x03')

def cmd_select_template(num: int): # ^TS 0NN     -> template 01..99
    if not (1 <= num <= 99):
        raise ValueError("Template number must be 1..99")
    tens, ones = divmod(num, 10)
    return _bcat(PREFIX, b'TS', b'0', bytes([48+tens]), bytes([48+ones]))

def cmd_set_delimiter(delim: str): # ^SS LL delim -> set delimiter, 1..20 chars
    if not (1 <= len(delim) <= 20):
        raise ValueError("Delimiter length must be 1..20")
    LL = f"{len(delim):02d}".encode("ascii")
    return _bcat(PREFIX, b'SS', LL, delim.encode('utf-8'))

def cmd_init_data():               # ^ID         -> init buffer
    return _bcat(PREFIX, b'ID')

def cmd_print():                   # ^FF         -> print
    return _bcat(PREFIX, b'FF')

def cmd_cut_options(auto_cut=True, cut_every=1, chain=False):  # ^CO n1 n2 n3 n4
    cut_every = max(1, min(99, int(cut_every)))
    tens, ones = divmod(cut_every, 10)
    n1 = b'1' if auto_cut else b'0'
    n4 = b'1' if chain else b'0'
    return _bcat(PREFIX, b'CO', n1, bytes([48+tens]), bytes([48+ones]), n4)

def cmd_select_object_by_name(name: str):      # ^ON name 00h
    if not (1 <= len(name) <= 20):
        raise ValueError("Object name must be 1..20 chars")
    return _bcat(PREFIX, b'ON', name.encode('utf-8'), b'\x00')

def cmd_direct_insert(text: str):              # ^DI n1 n2 data
    data = text.encode('utf-8')
    n = len(data)
    if n > 65534: raise ValueError("Text too long for ^DI")
    n1 = n & 0xFF
    n2 = (n >> 8) & 0xFF
    return _bcat(PREFIX, b'DI', bytes([n1, n2]), data)

# ---- Serial helpers ----
def list_serial_ports():
    """Return tuple(list_of_port_strings, preferred_index_or_-1)."""
    ports = list(list_ports.comports())
    names = [p.device for p in ports]
    # prefer Bluetooth-looking ports if present
    idx = -1
    for i, p in enumerate(ports):
        desc = (p.description or '').lower()
        hwid = (p.hwid or '').lower()
        if 'bluetooth' in desc or 'bth' in hwid:
            idx = i; break
    return names, idx

def open_bt_serial(port: str, baud=9600, timeout=3.0):
    if not port:
        raise RuntimeError("No COM port specified")
    return serial.Serial(port, baudrate=baud, timeout=timeout)

# ---- High-level jobs ----
def print_delimited(ser, template_num: int, values: list[str], delimiter: str=',',
                    auto_cut=True, cut_every=1):
    packet = b''.join([
        cmd_mode_template(),
        cmd_select_template(template_num),
        cmd_init_data(),
        cmd_set_delimiter(delimiter),
        cmd_cut_options(auto_cut=auto_cut, cut_every=cut_every),
        delimiter.encode('utf-8').join(v.encode('utf-8') for v in values),
        cmd_print()
    ])
    ser.write(packet); ser.flush()

def print_named(ser, template_num: int, fields: dict[str,str],
                auto_cut=True, cut_every=1):
    parts = [cmd_mode_template(), cmd_select_template(template_num), cmd_init_data(),
             cmd_cut_options(auto_cut, cut_every)]
    for obj_name, text in fields.items():
        parts.append(cmd_select_object_by_name(obj_name))
        parts.append(cmd_direct_insert(text))
    parts.append(cmd_print())
    ser.write(b''.join(parts)); ser.flush()
