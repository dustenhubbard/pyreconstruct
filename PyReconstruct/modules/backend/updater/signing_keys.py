"""The public keys that sign each release's ``SHA256SUMS``.

Two slots, so the signing key can be rotated. The main key signs every
release; its secret half lives only in the ``release`` GitHub environment, as
``UPDATE_SIGNING_KEY``. The backup key's secret half is kept offline and is
used only if the main key is lost or leaks: a release built with this version
already trusts it, so a client in the field can move to it without losing
verification.

Public keys are safe to publish. Each value is the second line of a minisign
``.pub`` file. The release job reads the same two strings to check its own
signature before publishing, and ``tests/test_signed_checksums.py`` keeps the
workflow and this module in step.
"""

# Key ID E9E080E669770C41.
MAIN = "RWRBDHdp5oDg6X8z9UrV+9/9lxyAu+oumUM+2ZWO0uPTzZOXAULNg5R1"

# Key ID 9521F6E9CFB39E8B.
BACKUP = "RWSLnrPP6fYhlcLSl/iYXcHAgH2PQC/EPVfI9l2CBFb8G35mY1UoyTUp"

TRUSTED_KEYS = (MAIN, BACKUP)
