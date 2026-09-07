# Native keyboard v2 and terminal display condition

This is an experiment-interface correction, not autonomous gameplay acceptance.
GPT-6 Astra Medium and the existing Codex subscription transport are unchanged.

The historical `native_keyboard/v1` catalog is retained for explicit comparisons.
It contained 358 hand-selected names. Native diagnostics found that `PAUSE` is
not a 0.47.05 interface event; `D_PAUSE` is. Building and workshop names also
needed a version-matched catalog, not individual aliases.

`native_keyboard/v2` exposes all 1,613 non-sentinel interface-event names from
DFHack 0.47.05-r8's pinned df-structures revision
`afe7e908e9e7e863412e8983f9feb2b999fae498`. See the provenance in
`fort_gym/bench/env/native_key_catalog.py`. An event being supported does not mean
it has an effect in every menu. No keys are repaired, substituted, or retried.
Both response parsing and dispatch validate the same declared catalog.

The catalog is supplied once in the prompt. The v2 output schema constrains the
response shape but does not enumerate all keys: OpenAI Structured Outputs allows
at most 1,000 enum values across a schema. The local parser still rejects any
unknown key before native dispatch. This does not reduce available controls.
Source: https://developers.openai.com/api/docs/guides/structured-outputs#limitations-on-enum-size

The native keyboard hook's additive `catalog` mode checks up to 2,048 candidate
names in one read-only call and reports every unsupported candidate. The existing
per-event receipt semantics are unchanged. Successful input receipts do not prove
that a building was placed, a job completed, or a fresh frame rendered.

The optional `screen_size=(120, 40)` runtime setting sizes the newly owned Linux
PTY before launching text-mode DF. It does not change the host terminal or the
retained game configuration. Default launch behavior remains unchanged.
The runtime receipt labels requested size separately; native CopyScreen evidence
must establish actual dimensions. Keep old 80x24 captures as separate conditions.

Required native check: full catalog compatibility, actual enlarged capture,
menu navigation, D_PAUSE with zero input-time ticks, explicit clock advancement,
unchanged source save, and complete runtime/VM teardown. A successful scripted
check is not an Astra campaign, workshop-ordering proof, or year-two acceptance.
