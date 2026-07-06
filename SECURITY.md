# Security Policy

Thanks for helping keep PyReconstruct and its users safe. This policy applies to
this distribution of PyReconstruct
([dustenhubbard/PyReconstruct](https://github.com/dustenhubbard/PyReconstruct)),
including its one-click installers and in-app updater.

## Supported versions

Security fixes land on the latest **Release** (stable) build, so the most reliable
way to stay protected is to run the current stable release and keep it up to date.

**Pre-release** builds are experimental and are fixed on a best-effort basis. If
you are on the Pre-release channel and hit a security issue, please still report
it; fixes there are not guaranteed to be as timely as on the Release channel.

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub, not in a public
issue or pull request:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** to open a new draft security advisory.
3. Describe the issue, the affected version or build, and steps to reproduce it.

This uses GitHub's private vulnerability reporting, so the report stays
confidential between you and the maintainer while it is being investigated.

Please do **not** open a public issue or pull request for a security problem, as
that would disclose it before a fix is available.

## What to expect

After you report a vulnerability, you can expect:

- **Acknowledgment** that the report was received.
- **Investigation** to confirm the issue and assess its impact.
- **A coordinated fix and disclosure.** Once a fix is ready, it is released and
  the issue is disclosed publicly, with a GitHub Security Advisory (and a CVE
  where warranted).
- **Credit** to you as the reporter, unless you prefer to remain anonymous.

## A note on update integrity

Installers and in-app updates are downloaded over HTTPS and are verified against a
published SHA-256 checksum before they are applied, so a corrupted or tampered
download is rejected rather than installed.
