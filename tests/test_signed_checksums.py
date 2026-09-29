"""Signed checksums: the release signs SHA256SUMS, PyReconstruct checks it.

The release job writes SHA256SUMS and update-manifest.json, signs SHA256SUMS
with minisign, and checks the signature against the two compiled-in public
keys before publishing. The updater fetches SHA256SUMS and its signature from
the same release and refuses the installer unless the signature is valid, made
by a trusted key, names this release's tag, and lists the installer. A frozen
build refuses a release with no signature; a source build keeps the per-file
.sha256 flow. The release job fails rather than publish without a signature.

The key pair under tests/fixtures/minisign/ is a throwaway made for these
tests with ``minisign -G -W``; ``other.*`` is a second one that PyReconstruct
does not trust. The committed ``.minisig`` files were made by the minisign CLI
(0.12), so the verifier is checked against the real tool on every run; the
tests that run minisign themselves skip where it is not installed.
"""
import base64
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.updater import minisign as M
from PyReconstruct.modules.backend.updater import signing_keys
from PyReconstruct.modules.backend.updater import signing_keys as SK_MODULE
from PyReconstruct.modules.backend.updater import updater as U

from test_pruning_preserves_release_tags import workflow_script

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "minisign"
WORKFLOW = ROOT / ".github" / "workflows" / "build-installers.yml"
SCRIPT = ROOT / "scripts" / "release_update_files.py"

TEST_PUB = (FIX / "test.pub").read_text()
OTHER_PUB = (FIX / "other.pub").read_text()
SUMS = (FIX / "SHA256SUMS").read_bytes()
TAG = "v1.24.0"
COMMENT = f"tag:{TAG} file:SHA256SUMS"
INSTALLER = "PyReconstruct-1.24.0-Windows-x86_64-Setup.exe"

MINISIGN = shutil.which("minisign") or (
    "/opt/homebrew/bin/minisign" if os.path.exists("/opt/homebrew/bin/minisign") else None
)
needs_minisign = pytest.mark.skipif(MINISIGN is None, reason="minisign CLI not installed")
needs_bash = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt",
                                reason="the release step is bash")


def sig(name):
    return (FIX / name).read_bytes()


def _lines(sigfile):
    return sigfile.decode().split("\n")


def _join(lines):
    return "\n".join(lines).encode()


# --- A signer for tests, from the minisign test key --------------------------
# The unencrypted minisign secret key is base64 of: "Ed", kdf "\0\0", "B2",
# salt[32], opslimit[8], memlimit[8], key_id[8], seed[32] + public key[32],
# checksum[32]. ``cryptography`` is a test-only convenience here (it arrives
# through cloud-volume); PyReconstruct itself never imports it.

def _test_signer():
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    raw = base64.b64decode((FIX / "test.key").read_text().splitlines()[1])
    return raw[54:62], ed.Ed25519PrivateKey.from_private_bytes(raw[62:94])


def make_sig(data, comment=COMMENT, prehash=True):
    key_id, sk = _test_signer()
    alg = b"ED" if prehash else b"Ed"
    signed = hashlib.blake2b(data, digest_size=64).digest() if prehash else data
    signature = sk.sign(signed)
    global_sig = sk.sign(signature + comment.encode())
    return (b"untrusted comment: test\n"
            + base64.b64encode(alg + key_id + signature) + b"\n"
            + b"trusted comment: " + comment.encode() + b"\n"
            + base64.b64encode(global_sig) + b"\n")


# --- The compiled-in keys ----------------------------------------------------

def test_two_key_slots_with_the_published_key_ids():
    assert signing_keys.TRUSTED_KEYS == (signing_keys.MAIN, signing_keys.BACKUP)
    ids = [M.key_id_hex(M.parse_public_key(k)[0]) for k in signing_keys.TRUSTED_KEYS]
    assert ids == ["E9E080E669770C41", "9521F6E9CFB39E8B"]


def test_the_release_step_checks_against_the_same_keys():
    text = WORKFLOW.read_text()
    block = text.split("UPDATE_PUBLIC_KEYS: >-\n", 1)[1].split("        run: |", 1)[0]
    assert tuple(block.split()) == signing_keys.TRUSTED_KEYS


# --- Ed25519 itself ----------------------------------------------------------

# RFC 8032, section 7.1, tests 1 to 3.
RFC_VECTORS = [
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("pk,msg,signature", RFC_VECTORS)
def test_rfc8032_vectors(pk, msg, signature):
    pk, msg, signature = bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(signature)
    assert M.ed25519_verify(pk, msg, signature)
    assert not M.ed25519_verify(pk, msg + b"x", signature)
    bad = bytearray(signature)
    bad[0] ^= 1
    assert not M.ed25519_verify(pk, msg, bytes(bad))


def test_agrees_with_an_independent_implementation():
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    from cryptography.hazmat.primitives import serialization
    rng = random.Random(434)
    for _ in range(20):
        sk = ed.Ed25519PrivateKey.from_private_bytes(rng.randbytes(32))
        pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        msg = rng.randbytes(rng.randrange(0, 200))
        assert M.ed25519_verify(pk, msg, sk.sign(msg))
        assert not M.ed25519_verify(pk, msg + b"\0", sk.sign(msg))


def test_a_non_reduced_s_is_refused():
    """S + L satisfies the same equation, so only the range check stops it."""
    pk, msg, signature = (bytes.fromhex(x) for x in RFC_VECTORS[0])
    s = int.from_bytes(signature[32:], "little") + M._L
    assert s < 2 ** 256
    assert not M.ed25519_verify(pk, msg, signature[:32] + s.to_bytes(32, "little"))


# Encodings of points of small order. The identity is (0, 1); (0, -1) has order 2.
SMALL_ORDER = {
    "identity": (1).to_bytes(32, "little"),
    "order 2": (M._P - 1).to_bytes(32, "little"),
}


def _any_message_signature():
    """R = B, S = 1: under the identity as a public key, [S]B - [h]A = B = R
    for every message, so only the small-order check refuses it."""
    return M._encode(M._BASE) + (1).to_bytes(32, "little")


def test_the_small_order_forgery_is_real_without_the_check():
    """The arithmetic accepts it, so the refusal below is the check's doing."""
    a = M._decode(SMALL_ORDER["identity"])
    for msg in (b"", b"anything", SUMS):
        h = int.from_bytes(hashlib.sha512(M._encode(M._BASE) + SMALL_ORDER["identity"] + msg).digest(),
                           "little") % M._L
        lhs = M._add(M._mul(1, M._BASE), M._negate(M._mul(h, a)))
        assert M._encode(lhs) == M._encode(M._BASE)


@pytest.mark.parametrize("name", sorted(SMALL_ORDER))
def test_a_small_order_public_key_is_refused(name):
    pk = SMALL_ORDER[name]
    assert M._decode(pk) is not None, "a valid point, just of small order"
    for msg in (b"", b"anything", SUMS):
        assert not M.ed25519_verify(pk, msg, _any_message_signature())


def test_a_minisign_signature_under_a_small_order_key_is_refused():
    """A whole forged .minisig for any file, under a key made of the identity."""
    key_id = b"\x01" * 8
    key = base64.b64encode(b"Ed" + key_id + SMALL_ORDER["identity"]).decode()
    forged = (b"untrusted comment: forged\n"
              + base64.b64encode(b"ED" + key_id + _any_message_signature()) + b"\n"
              + b"trusted comment: " + COMMENT.encode() + b"\n"
              + base64.b64encode(_any_message_signature()) + b"\n")
    with pytest.raises(M.BadSignature):
        M.verify(SUMS, forged, [key])


# --- Signatures made by the minisign CLI -------------------------------------

@pytest.mark.parametrize("name,algorithm", [("prehashed.minisig", b"ED"), ("legacy.minisig", b"Ed")])
def test_cli_signatures_of_both_algorithms_verify(name, algorithm):
    raw = base64.b64decode(_lines(sig(name))[1])
    assert raw[:2] == algorithm
    assert M.verify(SUMS, sig(name), [TEST_PUB]) == COMMENT


def test_either_key_slot_can_sign():
    assert M.verify(SUMS, sig("prehashed.minisig"), [OTHER_PUB, TEST_PUB]) == COMMENT
    assert M.verify(SUMS, sig("other-key.minisig"), [OTHER_PUB, TEST_PUB]) == COMMENT


def test_a_key_that_is_not_trusted_is_refused():
    with pytest.raises(M.UnknownKey):
        M.verify(SUMS, sig("other-key.minisig"), [TEST_PUB])
    with pytest.raises(M.UnknownKey):
        M.verify(SUMS, sig("prehashed.minisig"), signing_keys.TRUSTED_KEYS)


def test_the_same_key_id_with_another_key_is_refused():
    """A key ID is not an identity: the signature must check out under the key."""
    kid, _ = M.parse_public_key(TEST_PUB)
    _, other_pk = M.parse_public_key(OTHER_PUB)
    impostor = base64.b64encode(b"Ed" + kid + other_pk).decode()
    with pytest.raises(M.BadSignature):
        M.verify(SUMS, sig("prehashed.minisig"), [impostor])


@pytest.mark.parametrize("name", ["prehashed.minisig", "legacy.minisig"])
def test_a_tampered_sums_file_is_refused(name):
    tampered = SUMS.replace(b"b75b55e2", b"00000000")
    assert tampered != SUMS
    with pytest.raises(M.BadSignature):
        M.verify(tampered, sig(name), [TEST_PUB])
    with pytest.raises(M.BadSignature):
        M.verify(SUMS + b"\n", sig(name), [TEST_PUB])


@pytest.mark.parametrize("name", ["prehashed.minisig", "legacy.minisig"])
def test_an_edited_trusted_comment_is_refused(name):
    lines = _lines(sig(name))
    lines[2] = lines[2].replace(TAG, "v9.9.9")
    with pytest.raises(M.BadSignature, match="trusted comment"):
        M.verify(SUMS, _join(lines), [TEST_PUB])


def test_an_edited_untrusted_comment_is_ignored():
    lines = _lines(sig("prehashed.minisig"))
    lines[0] = "untrusted comment: anything at all"
    assert M.verify(SUMS, _join(lines), [TEST_PUB]) == COMMENT


def test_the_global_signature_is_checked():
    """A good file signature under someone else's global signature fails."""
    ours, wrong_tag = _lines(sig("prehashed.minisig")), _lines(sig("wrong-tag.minisig"))
    mixed = ours[:3] + [wrong_tag[3]] + ours[4:]
    with pytest.raises(M.BadSignature, match="trusted comment"):
        M.verify(SUMS, _join(mixed), [TEST_PUB])


def test_switching_the_algorithm_byte_is_refused():
    lines = _lines(sig("prehashed.minisig"))
    raw = bytearray(base64.b64decode(lines[1]))
    raw[1:2] = b"d"
    lines[1] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(M.BadSignature):
        M.verify(SUMS, _join(lines), [TEST_PUB])


def test_crlf_line_endings_are_accepted():
    crlf = sig("prehashed.minisig").replace(b"\n", b"\r\n")
    assert M.verify(SUMS, crlf, [TEST_PUB]) == COMMENT


def _malformed():
    good = _lines(sig("prehashed.minisig"))
    raw = base64.b64decode(good[1])
    cases = {
        "empty": b"",
        "garbage": b"\x00\xff" * 50,
        "three lines": _join(good[:3]),
        "five lines": _join(good[:4] + ["extra"]),
        "no untrusted prefix": _join(["comment: x"] + good[1:]),
        "no trusted prefix": _join(good[:2] + ["comment: " + COMMENT] + good[3:]),
        "bad base64": _join([good[0], "!!!!", good[2], good[3]]),
        "short signature": _join([good[0], base64.b64encode(raw[:-1]).decode(), good[2], good[3]]),
        "long signature": _join([good[0], base64.b64encode(raw + b"x").decode(), good[2], good[3]]),
        "unknown algorithm": _join([good[0], base64.b64encode(b"XX" + raw[2:]).decode(), good[2], good[3]]),
        "short global": _join(good[:3] + [base64.b64encode(b"x" * 63).decode()]),
        "huge comment": _join(good[:2] + ["trusted comment: " + "x" * 5000] + good[3:]),
        "not utf-8": _join(good[:2]).replace(b"untrusted", b"\xffntrusted") + b"\n" + _join(good[2:]),
        "public key where a signature goes": TEST_PUB.encode(),
    }
    return cases


@pytest.mark.parametrize("case", sorted(_malformed()))
def test_malformed_signatures_raise_signature_error(case):
    with pytest.raises(M.SignatureError):
        M.verify(SUMS, _malformed()[case], [TEST_PUB])


@pytest.mark.parametrize("key", ["", "not base64 !!", base64.b64encode(b"Ed" + b"x" * 39).decode(),
                                 base64.b64encode(b"XX" + b"x" * 40).decode()])
def test_malformed_public_keys_raise_signature_error(key):
    with pytest.raises(M.SignatureError):
        M.verify(SUMS, sig("prehashed.minisig"), [key])


def test_random_damage_never_escapes_as_another_exception():
    good = sig("prehashed.minisig")
    rng = random.Random(1)
    for _ in range(300):
        damaged = bytearray(good)
        for _ in range(rng.randint(1, 4)):
            damaged[rng.randrange(len(damaged))] = rng.randrange(256)
        try:
            M.verify(SUMS, bytes(damaged), [TEST_PUB])
        except M.SignatureError:
            pass


def test_non_bytes_input_is_a_signature_error():
    with pytest.raises(M.SignatureError):
        M.verify(None, sig("prehashed.minisig"), [TEST_PUB])
    with pytest.raises(M.SignatureError):
        M.verify(SUMS, None, [TEST_PUB])


@needs_minisign
@pytest.mark.parametrize("legacy", [False, True])
def test_a_fresh_cli_signature_verifies(tmp_path, legacy):
    data = tmp_path / "SHA256SUMS"
    data.write_bytes(os.urandom(3000))
    cmd = [MINISIGN, "-S", "-s", str(FIX / "test.key"), "-t", COMMENT, "-m", str(data)]
    subprocess.run(cmd + (["-l"] if legacy else []), check=True, stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=30)
    assert M.verify(data.read_bytes(), (tmp_path / "SHA256SUMS.minisig").read_bytes(),
                    [TEST_PUB]) == COMMENT


@needs_minisign
def test_a_signature_from_the_test_signer_passes_the_cli(tmp_path):
    """The in-test signer makes real minisign signatures, so the updater tests
    below that use it test the real format."""
    (tmp_path / "f").write_bytes(SUMS)
    (tmp_path / "f.minisig").write_bytes(make_sig(SUMS))
    subprocess.run([MINISIGN, "-V", "-q", "-p", str(FIX / "test.pub"), "-m", str(tmp_path / "f")],
                   check=True, capture_output=True, timeout=30)


# --- The updater flow --------------------------------------------------------

def _release(*names, tag=TAG, scheme="https"):
    return {"tag_name": tag, "assets": [
        {"name": n, "browser_download_url": f"{scheme}://github.com/o/r/releases/download/{tag}/{n}"}
        for n in names]}


def _serve(monkeypatch, files):
    """Serve ``files`` ({name: bytes}) through the real https/host check."""
    def fake_open(url, timeout):
        U._check_download_url(url)
        name = url.rsplit("/", 1)[1]
        if name not in files:
            raise RuntimeError("404")
        return _Resp(files[name])
    monkeypatch.setattr(U, "_open_download", fake_open)


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self, n=-1):
        return self._data if n < 0 else self._data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _signed(monkeypatch, signature, sums=SUMS, tag=TAG, keys=(TEST_PUB,)):
    files = {"SHA256SUMS": sums, "SHA256SUMS.minisig": signature}
    _serve(monkeypatch, files)
    rel = _release(INSTALLER, INSTALLER + ".sha256", "SHA256SUMS", "SHA256SUMS.minisig", tag=tag)
    return U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=keys)


def _expected():
    return hashlib.sha256(INSTALLER.encode()).hexdigest()


@pytest.mark.parametrize("name", ["prehashed.minisig", "legacy.minisig"])
def test_a_valid_signature_gives_the_signed_hash(monkeypatch, name):
    assert _signed(monkeypatch, sig(name)) == ("ok", _expected())


def test_an_invalid_signature_is_refused(monkeypatch):
    tampered = SUMS.replace(b"b75b55e2", b"00000000")
    assert _signed(monkeypatch, sig("prehashed.minisig"), sums=tampered) == ("bad_signature", None)


def test_a_signature_by_an_unknown_key_is_refused(monkeypatch):
    assert _signed(monkeypatch, sig("other-key.minisig")) == ("bad_signature", None)


def test_the_compiled_in_keys_are_the_default(monkeypatch):
    """The test key is not a release key, so its signature is refused by default."""
    _serve(monkeypatch, {"SHA256SUMS": SUMS, "SHA256SUMS.minisig": sig("prehashed.minisig")})
    rel = _release(INSTALLER, "SHA256SUMS", "SHA256SUMS.minisig")
    assert U.fetch_signed_checksum(rel, INSTALLER) == ("bad_signature", None)


def test_a_signature_for_another_tag_is_refused(monkeypatch):
    assert _signed(monkeypatch, sig("wrong-tag.minisig")) == ("bad_signature", None)
    assert _signed(monkeypatch, sig("prehashed.minisig"), tag="v1.25.0") == ("bad_signature", None)


def test_a_tampered_trusted_comment_is_refused(monkeypatch):
    lines = _lines(sig("prehashed.minisig"))
    lines[2] = lines[2].replace(TAG, "v1.25.0")
    assert _signed(monkeypatch, _join(lines), tag="v1.25.0") == ("bad_signature", None)


@pytest.mark.parametrize("comment", [
    "file:SHA256SUMS",                          # no tag at all
    f"tag:{TAG}",                               # no file
    f"tag:{TAG} file:update-manifest.json",     # a signature for another file
    f"tag:{TAG}x file:SHA256SUMS",              # a prefix is not a match
    f"timestamp:1\tfile:SHA256SUMS\thashed",    # minisign's default comment
])
def test_the_trusted_comment_must_name_this_tag_and_file(monkeypatch, comment):
    assert _signed(monkeypatch, make_sig(SUMS, comment)) == ("bad_signature", None)


def test_extra_fields_in_the_trusted_comment_are_fine(monkeypatch):
    comment = f"timestamp:1790700000 tag:{TAG} file:SHA256SUMS"
    assert _signed(monkeypatch, make_sig(SUMS, comment)) == ("ok", _expected())


def test_a_file_missing_from_sums_is_refused(monkeypatch):
    sums = b"".join(l + b"\n" for l in SUMS.splitlines() if INSTALLER.encode() not in l)
    assert _signed(monkeypatch, make_sig(sums), sums=sums) == ("unlisted", None)


@pytest.mark.parametrize("sums", [
    b"",
    b"\x00\xff garbage \x00\n" * 10,
    b"not-a-hash  " + INSTALLER.encode() + b"\n",
    b"a" * 63 + b"  " + INSTALLER.encode() + b"\n",
    b"a" * 64 + b" " + INSTALLER.encode() + b"\n",            # one space and no '*'
    b"a" * 64 + b"  " + INSTALLER.encode() + b".sha256\n",
    b"a" * 64 + b"  " + INSTALLER.encode() + b"\n"             # listed twice, differently
    + b"b" * 64 + b"  " + INSTALLER.encode() + b"\n",
])
def test_a_signed_but_malformed_sums_file_does_not_list_the_installer(monkeypatch, sums):
    assert _signed(monkeypatch, make_sig(sums), sums=sums) == ("unlisted", None)


def test_sums_lines_in_binary_mode_and_with_crlf_are_read(monkeypatch):
    sums = b"A" * 64 + b" *" + INSTALLER.encode() + b"\r\n"
    assert _signed(monkeypatch, make_sig(sums), sums=sums) == ("ok", "a" * 64)


def test_a_signature_without_its_sums_file_is_refused(monkeypatch):
    _serve(monkeypatch, {"SHA256SUMS.minisig": sig("prehashed.minisig")})
    rel = _release(INSTALLER, INSTALLER + ".sha256", "SHA256SUMS.minisig")
    assert U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=[TEST_PUB]) == ("bad_signature", None)


@pytest.mark.parametrize("missing", ["SHA256SUMS", "SHA256SUMS.minisig"])
def test_an_unreachable_signed_file_is_an_error(monkeypatch, missing):
    files = {"SHA256SUMS": SUMS, "SHA256SUMS.minisig": sig("prehashed.minisig")}
    del files[missing]
    _serve(monkeypatch, files)
    rel = _release(INSTALLER, "SHA256SUMS", "SHA256SUMS.minisig")
    assert U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=[TEST_PUB]) == ("error", None)


def test_the_download_rules_apply_to_the_signed_files(monkeypatch):
    _serve(monkeypatch, {"SHA256SUMS": SUMS, "SHA256SUMS.minisig": sig("prehashed.minisig")})
    rel = _release(INSTALLER, "SHA256SUMS", "SHA256SUMS.minisig", scheme="http")
    assert U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=[TEST_PUB]) == ("error", None)
    rel = _release(INSTALLER, "SHA256SUMS", "SHA256SUMS.minisig")
    for a in rel["assets"]:
        a["browser_download_url"] = a["browser_download_url"].replace("github.com", "example.com")
    assert U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=[TEST_PUB]) == ("error", None)


def test_an_oversized_signed_file_is_an_error(monkeypatch):
    _serve(monkeypatch, {"SHA256SUMS": b"x" * (U._MAX_SIGNED_BYTES + 1),
                         "SHA256SUMS.minisig": sig("prehashed.minisig")})
    rel = _release(INSTALLER, "SHA256SUMS", "SHA256SUMS.minisig")
    assert U.fetch_signed_checksum(rel, INSTALLER, trusted_keys=[TEST_PUB]) == ("error", None)


def test_the_signature_covers_the_exact_bytes(monkeypatch):
    """Bytes that do not decode as UTF-8 must not be repaired before checking."""
    sums = SUMS + b"\xff\xfe  junk\n"
    assert _signed(monkeypatch, make_sig(sums), sums=sums) == ("ok", _expected())


@pytest.fixture
def kind(monkeypatch):
    """Set what ``install_kind`` reports: ``kind("frozen")`` or ``kind("source")``."""
    import PyReconstruct.modules.backend.updater.install_info as II
    return lambda k: monkeypatch.setattr(II, "install_kind", lambda: k)


def test_no_signature_keeps_the_per_file_flow_in_a_source_build(monkeypatch, kind):
    kind("source")
    rel = _release(INSTALLER, INSTALLER + ".sha256")
    monkeypatch.setattr(U, "_download_bytes", lambda *a, **k: pytest.fail("no signed fetch"))
    monkeypatch.setattr(U, "_download_text", lambda url, timeout=15: "c0ffee  " + INSTALLER + "\n")
    assert U.fetch_signed_checksum(rel, INSTALLER) == ("absent", None)
    assert U.verified_checksum(rel, INSTALLER) == ("ok", "c0ffee")


def test_no_signature_and_no_checksum_is_still_missing_in_a_source_build(kind):
    kind("source")
    assert U.verified_checksum(_release(INSTALLER), INSTALLER) == ("missing", None)


def test_an_unsigned_sums_file_alone_keeps_the_old_fallback_in_a_source_build(monkeypatch, kind):
    """A release from a build without the key has SHA256SUMS but no signature."""
    kind("source")
    monkeypatch.setattr(U, "_download_text", lambda url, timeout=15: SUMS.decode())
    rel = _release(INSTALLER, "SHA256SUMS")
    assert U.verified_checksum(rel, INSTALLER) == ("ok", _expected())


@pytest.mark.parametrize("names", [
    (INSTALLER, INSTALLER + ".sha256"),                  # the signature deleted
    (INSTALLER, INSTALLER + ".sha256", "SHA256SUMS"),    # SHA256SUMS left unsigned
    (INSTALLER,),                                        # nothing at all
])
def test_a_frozen_build_refuses_a_release_with_no_signature(monkeypatch, kind, names):
    kind("frozen")
    monkeypatch.setattr(U, "_download_text", lambda *a, **k: pytest.fail("per-file fallback"))
    monkeypatch.setattr(U, "_download_bytes", lambda *a, **k: pytest.fail("nothing to fetch"))
    assert U.verified_checksum(_release(*names), INSTALLER) == ("unsigned", None)


@pytest.mark.parametrize("build", ["frozen", "source"])
def test_a_signed_release_verifies_in_either_build(monkeypatch, kind, build):
    kind(build)
    monkeypatch.setattr(SK_MODULE, "TRUSTED_KEYS", (TEST_PUB,))
    _serve(monkeypatch, {"SHA256SUMS": SUMS, "SHA256SUMS.minisig": sig("prehashed.minisig")})
    rel = _release(INSTALLER, INSTALLER + ".sha256", "SHA256SUMS", "SHA256SUMS.minisig")
    assert U.verified_checksum(rel, INSTALLER) == ("ok", _expected())


def test_a_published_signature_wins_over_the_per_file_checksum(monkeypatch):
    """With a bad signature the .sha256 beside the installer is never consulted."""
    monkeypatch.setattr(U, "_download_text", lambda *a, **k: pytest.fail("per-file fallback"))
    _serve(monkeypatch, {"SHA256SUMS": SUMS, "SHA256SUMS.minisig": sig("other-key.minisig")})
    rel = _release(INSTALLER, INSTALLER + ".sha256", "SHA256SUMS", "SHA256SUMS.minisig")
    assert U.verified_checksum(rel, INSTALLER) == ("bad_signature", None)


@pytest.mark.parametrize("release", [None, {}, {"assets": []}, {"assets": None}, {"assets": ["x", None]},
                                     {"tag_name": TAG}])
def test_empty_releases_have_no_signature(release):
    assert U.fetch_signed_checksum(release, INSTALLER) == ("absent", None)


# --- The update dialog -------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _dialog(tmp_path):
    from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog
    info = {
        "asset": {"name": INSTALLER, "browser_download_url": "https://github.com/x", "size": 1024},
        "release": _release(INSTALLER),
        "status": "newer",
        "remote_version": "1.24.0",
        "local_version": "1.23.0",
    }
    dlg = UpdateDialog(None, info, "release")
    dlg._parent = SimpleNamespace(_updater_pool=object(), _pending_installer=None,
                                  _pending_update_dir=None)
    dlg.show()
    tmpdir = tmp_path / "dl"
    tmpdir.mkdir()
    dest = tmpdir / INSTALLER
    dest.write_bytes(b"x")
    dlg._tmpdir = str(tmpdir)
    dlg._pool = object()
    return dlg, tmpdir, dest


REFUSALS = {
    "unsigned": "PyReconstruct couldn't verify this download (the release has no signature). Nothing was installed.",
    "bad_signature": "PyReconstruct couldn't verify this download (its signature is not valid). Nothing was installed.",
    "unlisted": "PyReconstruct couldn't verify this download (it is not in the signed checksum list). Nothing was installed.",
}


@pytest.mark.parametrize("status", sorted(REFUSALS))
def test_the_dialog_refuses_and_says_why(qapp, tmp_path, monkeypatch, status):
    import PyReconstruct.modules.gui.utils as gui_utils
    import PyReconstruct.modules.backend.updater.install_info as II
    notified = []
    monkeypatch.setattr(gui_utils, "notify", notified.append)
    monkeypatch.setattr(gui_utils, "notifyConfirm", lambda *a, **k: pytest.fail("no install anyway"))
    monkeypatch.setattr(II, "install_kind", lambda: "frozen")
    dlg, tmpdir, dest = _dialog(tmp_path)
    dlg._on_downloaded(("sha", status, None, str(dest)))
    assert notified == [REFUSALS[status]]
    assert dlg._parent._pending_installer is None
    assert not tmpdir.exists()


def test_refusal_text_follows_the_house_rules():
    for text in REFUSALS.values():
        assert "\u2014" not in text and "\u2013" not in text
        assert "the app" not in text.lower()
        assert text.startswith("PyReconstruct ")


def test_an_unreachable_checksum_says_try_again(qapp, tmp_path, monkeypatch):
    import PyReconstruct.modules.gui.utils as gui_utils
    notified = []
    monkeypatch.setattr(gui_utils, "notify", notified.append)
    dlg, tmpdir, dest = _dialog(tmp_path)
    dlg._on_downloaded(("sha", "error", None, str(dest)))
    assert notified == ["Couldn't verify the download (checksum unreachable). Not installing. Try again."]
    assert dlg._parent._pending_installer is None


def test_no_text_in_the_dialog_has_an_em_or_en_dash():
    """Every string literal, so window titles and messages alike."""
    import ast
    import PyReconstruct.modules.gui.dialog.update_dialog as D
    tree = ast.parse(Path(D.__file__).read_text())
    doc_nodes = {id(n.body[0].value) for n in ast.walk(tree)
                 if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
                 and n.body and isinstance(n.body[0], ast.Expr)}
    texts = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes]
    assert texts
    assert [t for t in texts if "\u2014" in t or "\u2013" in t] == []


def test_a_signed_hash_that_does_not_match_is_refused(qapp, tmp_path, monkeypatch):
    import PyReconstruct.modules.gui.utils as gui_utils
    notified = []
    monkeypatch.setattr(gui_utils, "notify", notified.append)
    dlg, tmpdir, dest = _dialog(tmp_path)
    dlg._on_downloaded(("a" * 64, "ok", "b" * 64, str(dest)))
    assert notified and "mismatch" in notified[0]
    assert dlg._parent._pending_installer is None


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in self._slots:
            fn(*args)


class _SyncPool:
    """Runs the dialog's download job at once, on this thread."""

    def createWorker(self, fn):
        self._fn = fn
        self._worker = SimpleNamespace(signals=SimpleNamespace(
            progress=_Signal(), result=_Signal(), error=_Signal()))
        return self._worker

    def start(self, worker):
        worker.signals.result.emit(self._fn())


def test_the_dialog_download_checks_the_signed_list(qapp, tmp_path, monkeypatch):
    """End to end through the dialog: a valid signature arms the installer."""
    import PyReconstruct.modules.gui.dialog.update_dialog as D
    from PyReconstruct.modules.backend.updater import signing_keys as SK
    body = b"installer bytes"
    digest = hashlib.sha256(body).hexdigest()
    sums = f"{digest}  {INSTALLER}\n".encode()
    monkeypatch.setattr(SK, "TRUSTED_KEYS", (TEST_PUB,))
    _serve(monkeypatch, {"SHA256SUMS": sums, "SHA256SUMS.minisig": make_sig(sums)})
    monkeypatch.setattr(U, "_download_text", lambda *a, **k: pytest.fail("per-file fallback"))

    def fake_download(url, dest, progress_cb=None, cancel_cb=None):
        Path(dest).write_bytes(body)
        return digest

    monkeypatch.setattr(D, "download_asset", fake_download)
    monkeypatch.setattr(D, "ThreadPool", _SyncPool)
    dlg, tmpdir, _ = _dialog(tmp_path)
    dlg._tmpdir = None
    dlg._release = _release(INSTALLER, INSTALLER + ".sha256", "SHA256SUMS", "SHA256SUMS.minisig")
    dlg._start_download()
    assert dlg._parent._pending_installer and dlg._parent._pending_installer.endswith(INSTALLER)
    shutil.rmtree(dlg._parent._pending_update_dir, ignore_errors=True)


# --- The release job ---------------------------------------------------------

def _fake_dist(root, ver="1.24.0", dev=""):
    dist = root / "dist"
    dist.mkdir()
    names = [f"PyReconstruct-{ver}-Windows-x86_64{dev}-Setup.exe",
             f"PyReconstruct-{ver}-macOS-arm64{dev}.dmg",
             f"PyReconstruct-{ver}-macOS-x86_64{dev}.dmg",
             f"PyReconstruct-{ver}-Linux-installer{dev}.tar.gz",
             f"PyReconstruct-{ver}-Linux-x86_64{dev}.AppImage"]
    for n in names:
        (dist / n).write_bytes(os.urandom(2048) + n.encode())
        (dist / f"{n}.sha256").write_text(f"{hashlib.sha256((dist / n).read_bytes()).hexdigest()}  {n}\n")
    (dist / "SHA256SUMS.minisig").write_text("stale from an earlier run\n")
    return dist, names


def _run_script(dist, tag, flavor):
    return subprocess.run([sys.executable, str(SCRIPT), str(dist), "--tag", tag, "--flavor", flavor],
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("tag,flavor,dev,version", [
    ("v1.24.0", "stable", "", "1.24.0"),
    ("v1.24.0.dev20260929", "dev", "-Dev", "1.24.0.dev20260929"),
    ("v1.24.0-rc.1", "stable", "", "1.24.0rc1"),
])
def test_the_script_writes_the_manifest_and_sums(tmp_path, tag, flavor, dev, version):
    dist, names = _fake_dist(tmp_path, version, dev)
    r = _run_script(dist, tag, flavor)
    assert r.returncode == 0, r.stderr

    manifest = json.loads((dist / "update-manifest.json").read_text())
    assert manifest == {
        "schema": 1, "tag": tag, "version": version, "flavor": flavor,
        "platforms": {p: {"inplace": {"enabled": False}, "min_client": version}
                      for p in ("windows-x86_64", "macos-arm64", "macos-x86_64", "linux-x86_64")},
    }

    listed = [l.split("  ", 1) for l in (dist / "SHA256SUMS").read_text().splitlines()]
    expected = sorted(names + ["update-manifest.json"], key=str.encode)
    assert [n for _, n in listed] == expected
    for digest, n in listed:
        assert digest == hashlib.sha256((dist / n).read_bytes()).hexdigest()
    assert not (dist / "SHA256SUMS.minisig").exists(), "a stale signature must not survive"
    assert (dist / "SHA256SUMS").read_bytes().endswith(b"\n")
    assert b"\r" not in (dist / "SHA256SUMS").read_bytes()


def test_sha256sum_reads_the_list(tmp_path):
    tool = (["sha256sum", "-c"] if shutil.which("sha256sum")
            else ["shasum", "-a", "256", "-c"] if shutil.which("shasum") else None)
    if tool is None:
        pytest.skip("no sha256sum or shasum")
    dist, _ = _fake_dist(tmp_path)
    assert _run_script(dist, TAG, "stable").returncode == 0
    r = subprocess.run(tool + ["SHA256SUMS"], cwd=dist, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_unknown_flavor_fails_the_script(tmp_path):
    dist, _ = _fake_dist(tmp_path)
    r = _run_script(dist, TAG, "Dev")
    assert r.returncode != 0
    assert not (dist / "SHA256SUMS").exists()


def _step_env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("UPDATE_")}
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    env["GITHUB_REF_NAME"] = TAG
    env.update(extra)
    return env


def _stage_repo(tmp_path, flavor):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "packaging").mkdir()
    if flavor is not None:
        (tmp_path / "packaging" / "FLAVOR").write_text(flavor + "\n")


@needs_bash
@pytest.mark.parametrize("flavor_file,flavor", [("dev", "dev"), (None, "stable")])
def test_the_manifest_step_reads_the_flavor(tmp_path, flavor_file, flavor):
    _stage_repo(tmp_path, flavor_file)
    _fake_dist(tmp_path)
    script = workflow_script(WORKFLOW.name, "Write the update manifest and SHA256SUMS")
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=tmp_path,
                       env=_step_env(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "dist" / "update-manifest.json").read_text())["flavor"] == flavor


def _sign_step(tmp_path, key_text, public_keys=None):
    script = workflow_script(WORKFLOW.name, "Sign SHA256SUMS")
    env = _step_env(tmp_path, MINISIGN=MINISIGN or "minisign",
                    UPDATE_SIGNING_KEY=key_text,
                    UPDATE_PUBLIC_KEYS=public_keys or TEST_PUB.splitlines()[1])
    return subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)


def _secret_line(name="test.key"):
    return (FIX / name).read_text().splitlines()[1]


@needs_bash
@needs_minisign
@pytest.mark.parametrize("form", ["file", "base64 line only", "crlf"])
def test_the_sign_step_signs_and_the_updater_accepts_it(tmp_path, monkeypatch, form):
    dist, names = _fake_dist(tmp_path)
    assert _run_script(dist, TAG, "stable").returncode == 0
    key = (FIX / "test.key").read_text()
    key = {"file": key, "base64 line only": _secret_line(), "crlf": key.replace("\n", "\r\n")}[form]
    r = _sign_step(tmp_path, key)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _secret_line() not in r.stdout + r.stderr
    assert f"trusted comment: {COMMENT}" in r.stdout

    sums, signature = (dist / "SHA256SUMS").read_bytes(), (dist / "SHA256SUMS.minisig").read_bytes()
    assert M.verify(sums, signature, [TEST_PUB]) == COMMENT
    _serve(monkeypatch, {"SHA256SUMS": sums, "SHA256SUMS.minisig": signature})
    rel = _release(*sorted(p.name for p in dist.iterdir()))
    for n in names:
        assert U.fetch_signed_checksum(rel, n, trusted_keys=[TEST_PUB]) == (
            "ok", hashlib.sha256((dist / n).read_bytes()).hexdigest())
    assert U.fetch_signed_checksum(rel, "update-manifest.json", trusted_keys=[TEST_PUB])[0] == "ok"
    assert U.fetch_signed_checksum(rel, names[0] + ".sha256", trusted_keys=[TEST_PUB])[0] == "unlisted"


@needs_bash
@needs_minisign
def test_the_sign_step_fails_on_a_key_that_is_not_trusted(tmp_path):
    dist, _ = _fake_dist(tmp_path)
    assert _run_script(dist, TAG, "stable").returncode == 0
    r = _sign_step(tmp_path, (FIX / "other.key").read_text())
    assert r.returncode != 0
    assert "does not verify against a key PyReconstruct trusts" in r.stdout
    assert _secret_line("other.key") not in r.stdout + r.stderr


@needs_bash
def test_the_sign_step_fails_without_a_key(tmp_path):
    """A v* release must never publish unsigned: a frozen client refuses it."""
    dist, _ = _fake_dist(tmp_path)
    assert _run_script(dist, TAG, "stable").returncode == 0
    r = _sign_step(tmp_path, "")
    assert r.returncode == 1
    assert "::error::UPDATE_SIGNING_KEY is not set" in r.stdout
    assert not (dist / "SHA256SUMS.minisig").exists()


def test_the_sign_step_never_prints_or_stores_the_key():
    script = workflow_script(WORKFLOW.name, "Sign SHA256SUMS")
    assert "set -x" not in script and "set -o xtrace" not in script
    uses = [l for l in script.splitlines() if "UPDATE_SIGNING_KEY" in l]
    allowed = ('if [ -z "${UPDATE_SIGNING_KEY:-}" ]; then',
               '"untrusted comment:"*) printf \'%s\\n\' "$UPDATE_SIGNING_KEY" ;;',
               "*) printf 'untrusted comment: minisign secret key\\n%s\\n' \"$UPDATE_SIGNING_KEY\" ;;",
               'case "$UPDATE_SIGNING_KEY" in',
               "unset UPDATE_SIGNING_KEY",
               'echo "::error::UPDATE_SIGNING_KEY is not set; a v* release must not publish unsigned"')
    for line in uses:
        assert line.strip() in allowed, line
    assert "-s <(secret_key)" in script, "the key goes to minisign through a pipe"
    assert ">" not in script.split("secret_key() {", 1)[1].split("}", 1)[0].replace("2>", "")


def test_minisign_is_pinned_by_hash():
    text = WORKFLOW.read_text()
    step = text.split("- name: Install minisign\n", 1)[1].split("\n      - name:", 1)[0]
    assert "MINISIGN_URL: https://github.com/jedisct1/minisign/releases/download/0.12/" in step
    assert "MINISIGN_SHA256: 9a599b48ba6eb7b1e80f12f36b94ceca7c00b7a5173c95c3efc88d9822957e73" in step
    assert 'sha256sum -c -' in step


def test_release_steps_run_in_order():
    text = WORKFLOW.read_text()
    release = text.split("\n  release:\n", 1)[1]
    order = ["- name: Generate checksums", "- name: Write the update manifest and SHA256SUMS",
             "- name: Install minisign", "- name: Sign SHA256SUMS",
             "- uses: softprops/action-gh-release"]
    positions = [release.index(s) for s in order]
    assert positions == sorted(positions)


def test_the_frozen_selftest_covers_the_verifier():
    assert M.selftest(signing_keys.TRUSTED_KEYS)
    assert not M.selftest(["not a key"])
    run = (ROOT / "PyReconstruct" / "run.py").read_text()
    selftest = run.split('elif "--selftest" in sys.argv[1:]:', 1)[1].split("else:", 1)[0]
    assert "_minisign.selftest(TRUSTED_KEYS)" in selftest


def _release_job():
    text = WORKFLOW.read_text()
    return text[text.index("\n  release:\n"):text.index("\n  readme-bump:\n")]


def test_every_pip_install_in_the_release_job_is_hash_pinned_to_the_lock():
    """The release job holds the signing key's environment, so nothing it
    installs may float: pip gets the exact wheel uv.lock resolves, by hash."""
    import re
    import tomllib
    job = _release_job()
    installs = re.findall(r"pip install[^\n]*", job.replace("\\\n", " "))
    assert installs, "is this test stale?"
    for cmd in installs:
        for flag in ("--require-hashes", "--no-deps", "--only-binary :all:", "-r "):
            assert flag in cmd, (flag, cmd)
    pins = re.findall(r"([A-Za-z0-9_.-]+)==(\S+) --hash=sha256:([0-9a-f]{64})", job)
    assert pins
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    for name, version, digest in pins:
        pkg = next(p for p in lock["package"] if p["name"] == name)
        assert pkg["version"] == version, name
        assert f"sha256:{digest}" in [w["hash"] for w in pkg.get("wheels", [])], name
    assert "pip install" not in job.replace("python3 -m pip install", ""), "only through python3 -m pip"


def test_every_action_in_the_release_job_is_pinned_to_a_commit():
    import re
    uses = re.findall(r"uses: (\S+)(.*)", _release_job())
    assert len(uses) == 3, uses
    for action, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action
        assert re.search(r"#\s*v\d", rest), (action, "no version comment")
