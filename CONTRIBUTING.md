# Code review and contributing

The project is intentionally small: `registry/core.py` has the pure node identity and filter rules; `registry/app.py` is the API, scheduler, snapshots and publication pipeline; `registry/static/` is the browser UI. Sub-Store's API provides parsing and serialization; the project does not implement proxy protocols itself.

## Review before deploying

1. Inspect `install.sh`, `setup.sh`, `compose.yaml`, `Caddyfile` and `.env.example` before running commands as root.
2. Check that Docker ports only expose `80:80` and `443:443` and that Sub-Store's port `3000` and Registry's port `8000` have no host mappings.
3. Confirm `.env`, `data/` and `backups/` are not tracked. Do not paste provider subscriptions or feed URLs in public issues.
4. Review `registry/core.py` fingerprint semantics when changing node fields: a change can affect persistent exclusions.
5. Run `python -m pytest -q registry/tests` and `bash -n install.sh setup.sh update.sh backup.sh`.
6. Test actual Sub-Store and iOS Loon before replacing a working live profile.

There are no code-path triggers for automatic speed checks or proxy data-plane forwarding.

**Deployment policy:** install from an audited full commit SHA where possible. A mutable `main` archive is convenient for evaluation but should not be considered a reproducible release without a pinned hash.
