# Fort Labs social cards

Run `python scripts/generate_social_assets.py` from the repository root to
rebuild the checked-in page cards and app icons.

`first-g4-pass-screen.txt` is recorded CopyScreen evidence from step 63 of the
first G4 pass, public replay token
`qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH`. It is not an Observer Map or a synthetic
fortress. Static page cards use that fixed evidence frame. Individual replay
cards are rendered on request from the bounded `/preview` frame for that exact
public run.

`provenance.json` binds the checked-in frame to its source run, source trace,
and exact `screen_text` bytes with SHA-256 hashes. The frame file has a normal
trailing newline; its declared hash covers the source field without that newline.

Every social card is a `1200x630` PNG. Update `CARD_VERSION` and the `?v=` URLs
when changing the image contract so social-crawler caches receive a new URL.
