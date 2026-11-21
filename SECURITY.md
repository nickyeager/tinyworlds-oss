# Security

TinyWorlds executes generated code and can call paid asset services. Public
hosting must use the isolation, scoped credentials, budget controls and separate
playback origin described in [the generation guide](docs/guides/generation.md).
Local development configuration is not a public-hosting configuration.

Do not put credentials, exploit details or private user data in a public issue.
Use [GitHub's private vulnerability reporting](https://github.com/nickyeager/tinyworlds-oss/security/advisories/new)
for this repository.

A useful private report identifies the affected revision, reproducible behavior,
impact and relevant redacted logs. Do not test against the live service or
other people's games without authorization.

Before publishing a release, scan both the intended file snapshot and Git
history. Deleting a secret from the latest file does not remove it from history.
A scanner finding needs triage; a clean scanner result is not a security audit.
