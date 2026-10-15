"""Minimal RFB (VNC) client: grab one framebuffer and save it as PNG.

Used for live Agent Desktop previews from both backends (TigerVNC Xvnc inside
containers, QEMU's VNC server for VMs), over a local Unix socket with
security type None. Only Raw encoding is requested, so the client is tiny.
"""
import socket
import struct


class RFBError(RuntimeError):
    pass


def _recv(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RFBError("connection closed")
        buf += chunk
    return bytes(buf)


def grab(path, timeout=5.0, max_pixels=3840 * 2400):
    """Return (width, height, rgb_bytes) of the current screen."""
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect(path)
        ver = _recv(s, 12)
        if not ver.startswith(b"RFB "):
            raise RFBError("not an RFB server")
        s.sendall(b"RFB 003.008\n")
        n = _recv(s, 1)[0]
        if n == 0:
            (ln,) = struct.unpack(">I", _recv(s, 4))
            raise RFBError(_recv(s, ln).decode("utf-8", "replace"))
        types = _recv(s, n)
        if 1 not in types:
            raise RFBError("server requires authentication")
        s.sendall(b"\x01")
        (result,) = struct.unpack(">I", _recv(s, 4))
        if result != 0:
            raise RFBError("security handshake failed")
        s.sendall(b"\x01")  # ClientInit: shared session (do not disconnect viewers)
        w, h = struct.unpack(">HH", _recv(s, 4))
        _recv(s, 16)  # server pixel format (we set our own)
        (nlen,) = struct.unpack(">I", _recv(s, 4))
        _recv(s, nlen)
        if w * h > max_pixels or w == 0 or h == 0:
            raise RFBError(f"unexpected framebuffer size {w}x{h}")
        # SetPixelFormat: 32bpp, depth 24, little endian, true colour, RGB shifts 16/8/0.
        s.sendall(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        s.sendall(struct.pack(">BxHi", 2, 1, 0))  # SetEncodings: Raw only
        s.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))  # full, non-incremental update
        fb = bytearray(w * h * 4)
        while True:
            mtype = _recv(s, 1)[0]
            if mtype == 0:
                break
            if mtype == 2:  # bell
                continue
            if mtype == 3:  # cut text
                _recv(s, 3)
                (ln,) = struct.unpack(">I", _recv(s, 4))
                _recv(s, ln)
                continue
            raise RFBError(f"unexpected message {mtype}")
        _recv(s, 1)
        (nrects,) = struct.unpack(">H", _recv(s, 2))
        for _ in range(nrects):
            x, y, rw, rh, enc = struct.unpack(">HHHHi", _recv(s, 12))
            if enc != 0:
                raise RFBError(f"unexpected encoding {enc}")
            data = _recv(s, rw * rh * 4)
            for row in range(rh):
                off = ((y + row) * w + x) * 4
                fb[off:off + rw * 4] = data[row * rw * 4:(row + 1) * rw * 4]
        # BGRX (little endian, shifts 16/8/0) -> RGB
        rgb = bytearray(w * h * 3)
        rgb[0::3] = fb[2::4]
        rgb[1::3] = fb[1::4]
        rgb[2::3] = fb[0::4]
        return w, h, bytes(rgb)
    finally:
        s.close()


def grab_png(sock_path, png_path, max_width=1280):
    from PIL import Image
    w, h, rgb = grab(sock_path)
    im = Image.frombytes("RGB", (w, h), rgb)
    if w > max_width:
        im = im.resize((max_width, int(h * max_width / w)))
    im.save(png_path, optimize=True)
    return png_path
