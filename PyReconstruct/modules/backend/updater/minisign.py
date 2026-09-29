"""Check a minisign signature, with no dependencies beyond the standard library.

Each release publishes ``SHA256SUMS`` and ``SHA256SUMS.minisig``. The
signature is made by the release job with ``minisign -S`` and checked here
against the public keys compiled into PyReconstruct (``signing_keys``), so
the checksums the updater trusts come from whoever holds the signing key and
not from whoever can upload a file to the release.

Stdlib only, on purpose. ``cryptography`` is in the lock file only because
cloud-volume's Google dependencies pull it in, so it is not a promise the
frozen builds keep, and the in-place helper (``apply.py``) is stdlib only
too. Verification needs no secret, so the Ed25519 code below does not try to
run in constant time; it is plain RFC 8032 arithmetic on Python integers and
takes a few milliseconds.

A minisign signature file has four lines::

    untrusted comment: <anything>
    base64(algorithm[2] + key_id[8] + signature[64])
    trusted comment: <text>
    base64(global_signature[64])

The algorithm is ``Ed`` (the signature covers the file itself) or ``ED`` (it
covers the file's BLAKE2b-512 hash, minisign's default since 0.10). The
global signature covers the first signature followed by the trusted comment,
so the trusted comment cannot be changed without the key. A public key is
``base64("Ed" + key_id[8] + public_key[32])``; minisign prints the key ID as
the eight bytes read as a little-endian number.
"""

import base64
import binascii
import hashlib


class SignatureError(Exception):
    """The signature does not check out. Subclasses say why."""


class MalformedSignature(SignatureError):
    """The signature file, or a public key, is not in minisign's format."""


class UnknownKey(SignatureError):
    """The signature was made by a key PyReconstruct does not trust."""


class BadSignature(SignatureError):
    """The signature is well formed but does not match the file."""


_UNTRUSTED_PREFIX = b"untrusted comment: "
_TRUSTED_PREFIX = b"trusted comment: "
_LEGACY = b"Ed"
_PREHASHED = b"ED"
# minisign itself refuses comments longer than this.
_MAX_COMMENT = 1024


# --- Ed25519 verification (RFC 8032, section 5.1) ----------------------------

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y, sign):
    """The x for ``y`` with the given low bit, or None if there is none."""
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


# Points are in extended coordinates (X, Y, Z, T) with x = X/Z, y = Y/Z,
# x * y = T/Z.
_BY = 4 * pow(5, _P - 2, _P) % _P
_BASE = (_recover_x(_BY, 0), _BY, 1, _recover_x(_BY, 0) * _BY % _P)
_IDENTITY = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(k, p):
    q = _IDENTITY
    while k:
        if k & 1:
            q = _add(q, p)
        p = _add(p, p)
        k >>= 1
    return q


def _negate(p):
    return (-p[0] % _P, p[1], p[2], -p[3] % _P)


def _encode(p):
    zi = pow(p[2], _P - 2, _P)
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(s):
    """The point encoded in ``s``, or None if it is not a canonical encoding."""
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def ed25519_verify(public_key, message, signature):
    """True when ``signature`` is a valid Ed25519 signature of ``message``.

    The check is the one libsodium makes: S must be reduced, the public key
    must be a canonical point outside the small subgroup, and ``[S]B - [h]A``
    must encode to exactly the R bytes in the signature.
    """
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode(public_key)
    if a is None or _encode(_mul(8, a)) == _encode(_IDENTITY):
        return False
    r_bytes, s = signature[:32], int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(r_bytes + public_key + message).digest(), "little") % _L
    return _encode(_add(_mul(s, _BASE), _negate(_mul(h, a)))) == r_bytes


# --- minisign ----------------------------------------------------------------

def _b64(data, length, what):
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise MalformedSignature(f"{what} is not valid base64")
    if len(raw) != length:
        raise MalformedSignature(f"{what} has the wrong length")
    return raw


def parse_public_key(text):
    """``(key_id, public_key)`` from a minisign public key.

    Takes the base64 line alone or a whole ``.pub`` file (the base64 line is
    the last non-empty one).
    """
    if isinstance(text, bytes):
        text = text.decode("ascii", "replace")
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        raise MalformedSignature("public key is empty")
    raw = _b64(lines[-1], 42, "public key")
    if raw[:2] != _LEGACY:
        raise MalformedSignature("public key is not an Ed25519 minisign key")
    return raw[2:10], raw[10:]


def key_id_hex(key_id):
    """The key ID as minisign prints it, such as ``E9E080E669770C41``."""
    return key_id[::-1].hex().upper()


def verify(message, signature_file, trusted_keys):
    """Check a minisign signature of ``message``; return its trusted comment.

    ``signature_file`` is the ``.minisig`` content (bytes or str) and
    ``trusted_keys`` the public keys to accept, in the forms
    :func:`parse_public_key` takes. Raises :class:`MalformedSignature`,
    :class:`UnknownKey`, or :class:`BadSignature`, all
    :class:`SignatureError`, and nothing else for any input. The trusted
    comment comes back as text, decoded from UTF-8.
    """
    if isinstance(signature_file, str):
        signature_file = signature_file.encode("utf-8", "replace")
    if not isinstance(message, (bytes, bytearray)) or not isinstance(signature_file, bytes):
        raise MalformedSignature("message and signature must be bytes")

    lines = [l.rstrip(b"\r") for l in signature_file.split(b"\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) != 4:
        raise MalformedSignature("signature file does not have four lines")
    untrusted, sig_line, trusted, global_line = lines
    if not untrusted.startswith(_UNTRUSTED_PREFIX):
        raise MalformedSignature("signature file has no untrusted comment line")
    if not trusted.startswith(_TRUSTED_PREFIX):
        raise MalformedSignature("signature file has no trusted comment line")
    comment = trusted[len(_TRUSTED_PREFIX):]
    if len(comment) > _MAX_COMMENT:
        raise MalformedSignature("trusted comment is too long")

    sig = _b64(sig_line.strip(), 74, "signature")
    global_sig = _b64(global_line.strip(), 64, "global signature")
    algorithm, key_id, signature = sig[:2], sig[2:10], sig[10:]
    if algorithm not in (_LEGACY, _PREHASHED):
        raise MalformedSignature("signature uses an unknown algorithm")

    public_key = None
    for key in trusted_keys:
        kid, pk = parse_public_key(key)
        if kid == key_id:
            public_key = pk
            break
    if public_key is None:
        raise UnknownKey(f"signed by unknown key {key_id_hex(key_id)}")

    signed = bytes(message)
    if algorithm == _PREHASHED:
        signed = hashlib.blake2b(signed, digest_size=64).digest()
    if not ed25519_verify(public_key, signed, signature):
        raise BadSignature("signature does not match the file")
    if not ed25519_verify(public_key, signature + comment, global_sig):
        raise BadSignature("trusted comment does not match its signature")
    return comment.decode("utf-8", "replace")


# RFC 8032, section 7.1, test 1: an empty message.
_RFC_PK = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
_RFC_SIG = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)


def selftest(trusted_keys):
    """True when verification works in this build and every key parses.

    Run by ``--selftest``, so a frozen build that lost BLAKE2b or SHA-512,
    or shipped a key that does not parse, fails in CI rather than at a
    user's first update.
    """
    try:
        hashlib.blake2b(b"", digest_size=64).digest()
        for key in trusted_keys:
            parse_public_key(key)
        return (ed25519_verify(_RFC_PK, b"", _RFC_SIG)
                and not ed25519_verify(_RFC_PK, b"x", _RFC_SIG))
    except Exception:
        return False
