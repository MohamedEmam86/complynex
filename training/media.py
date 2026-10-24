"""
Video length read on the server from an uploaded MP4/MOV file (no external
tools needed: the length is in the 'mvhd' header box of the 'moov' box).
Returns whole seconds, or None when the file is not an MP4 or cannot be read
(the training administrator then enters the length on the course form).
"""

import struct

_CONTAINERS = (b'moov',)


def _boxes(f, start, end):
    """Yield (type, payload_start, box_end) for the boxes between start and end."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size, btype = struct.unpack('>I4s', head)
        hdr = 8
        if size == 1:
            big = f.read(8)
            if len(big) < 8:
                return
            size = struct.unpack('>Q', big)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            return
        yield btype, pos + hdr, min(pos + size, end)
        pos += size


def mp4_duration_seconds(path):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            total = f.tell()
            for btype, body, bend in _boxes(f, 0, total):
                if btype != b'moov':
                    continue
                for itype, ibody, _iend in _boxes(f, body, bend):
                    if itype != b'mvhd':
                        continue
                    f.seek(ibody)
                    version = f.read(1)
                    if not version:
                        return None
                    f.read(3)  # flags
                    if version[0] == 1:
                        f.read(16)
                        timescale, duration = struct.unpack('>IQ', f.read(12))
                    else:
                        f.read(8)
                        timescale, duration = struct.unpack('>II', f.read(8))
                    if not timescale or not duration or duration in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                        return None
                    secs = int(round(duration / float(timescale)))
                    return secs if secs > 0 else None
    except (OSError, struct.error, ValueError):
        return None
    return None
