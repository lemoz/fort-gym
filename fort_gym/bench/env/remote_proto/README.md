# DFHack Remote Protocol Assets

This folder keeps lightweight helpers for managing the protobuf definitions required to talk
to DFHack's Remote API and the `RemoteFortressReader` plugin.

## Generating bindings

1. Ensure `protobuf` and `grpcio-tools` are installed in your environment.
2. Run `make proto` (or execute `python -m fort_gym.bench.env.remote_proto.fetch_proto`).
3. Generated python files will appear under `fort_gym/bench/env/remote_proto/gen/`.

The script fetches the `.proto` sources directly from the DFHack repository for the configured
release (`52.04-r1` by default). Generated assets are **not** committed to source control.
