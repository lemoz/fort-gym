# Year-Two delivery audit

Snapshot: September 12, 2026 UTC, goal branch
`aa51f6478` before this documentation update.
This is a progress audit, not a completion certificate or a replacement goal.
Requirements come from [the approved goal](YEAR_TWO_CAMPAIGNS.md),
[the standard-input phase](ASTRA_STANDARD_INPUT_EXPERIMENTS.md), and the
[frozen displayed-key cohort](../experiments/keyboard_binding_comparison_20260911/cohort.json).

## Evidence and remaining work

Latest update: [public-owner acceptance](../experiments/evidence/keyboard_portable_owner_acceptance_20260912.json)
passed at integration source `40b106b95f483b534a738622e75c4147a1270a96`.
The CLI performed a real two-decision Astra fresh window, saved checkpoint2,
then reloaded its own save and retained checkpoint4 after two more decisions.
The audit reconciles 95,786 tokens, memory, history, native load and owned
teardown. This closes the public-owner end-to-end acceptance gap in the older
snapshot below. Two startup failures and their fixes remain explicitly retained.
Full local tests: 5,530 passed / 10 skipped. Exact-head hosted CI: 5,386 passed /
154 skipped. No new growth is claimed: the game stayed paused during these four
navigation/designation decisions. Portable observer wiring, source review,
main merge and the remaining gameplay/comparison goals are still open.

| Requirement | Current evidence | Remaining work or limit |
| --- | --- | --- |
| Autonomous functioning fortress after a full elapsed year, continuing past its anniversary | The [displayed-key Astra result](../experiments/evidence/keyboard_binding_astra_r1_continuation_256_416_20260911.json) retains 429,845 ticks, 13 living citizens, zero recorded deaths, 12 beds, three workshops and one farm, without human gameplay rescue. Twenty-three post-anniversary samples support a qualitative operating-at-endpoint assessment. | This achieved milestone is one exploratory campaign, not a matched replicate or proof of indefinite self-sufficiency. Preserve its disclosed earlier save loss. Continue the longer-play investigation; do not rerun baseline acceptance to replace gameplay. |
| Persistent save/resume with memory and honest budget accounting | [Checkpoint 416's later native reload](../experiments/evidence/keyboard_binding_astra_r1_reload_416_20260911.json) preserves the fortress, memory, prompt, history and cumulative usage. [Terra's completed checkpoint128](../experiments/evidence/keyboard_binding_comparison_terra_r1_128_20260912.json) passed its terminal audit and teardown after a verified native parent load. [Astra's next startup](../experiments/evidence/matched_continuation_astra_r1_startup_20260912.json) also passed that load gate. | [Astra's checkpoint128](../experiments/evidence/keyboard_binding_comparison_astra_r1_128_20260912.json) now passed its terminal audit and teardown as well. Neither new final checkpoint has had a separate fresh reload. Retain Sol's failed startup and its native dispatch counter separately from zero new provider calls. |
| Three configuration-selected models and repeated comparable attempts | The [index](../experiments/evidence/keyboard_binding_comparison_20260911_index.json) and reader verify six audited fresh 64-response outcomes, two each for Astra, Sol and Terra. Conditions share seed, source/image, Medium effort, prompt, screen, controls and ceilings. | The declared 128-response comparison now retains five outcomes: three saved continuations and two Sol startup infrastructure failures. Sol r2 stopped below the unchanged guest capacity floor before a game or model call; its original save remains intact. Astra r2 is unlaunched while that shortage remains. Do not present an infrastructure failure as model collapse or remove it from the denominator. |
| Standard input versus optional shortcuts | This cohort explicitly uses displayed native keyboard controls and excludes shortcuts. The standard-input phase preserves a separate three-pair comparison with explicit shortcuts. | That paired comparison is not proved by these six model trials. Declare and run it separately with matching starts and budgets; do not alter the current cohort or silently introduce helpers. |
| Inspectable development, adaptation and sustainability | Saved native metrics, job samples, elapsed time, chosen controls and rejected actions are retained and replayable. The Astra endpoint review explicitly qualifies its observations. | Stocks and sampled jobs are not production/consumption rates, accessible reserves or completed job counts. Keep unmeasured fields unknown; use longer gameplay and separately versioned measurement improvements for stronger sustainability claims. |
| Honest cost and resource reporting | Returned model tokens and known lost responses remain accounted. Results identify subscription transport and leave dollar charges null. | Subscription dollar charges, hardware energy and app cost are unreported, not zero. Do not create a fabricated actual cost or silently substitute API-price estimates. |
| Live and recorded website delivery | [The verified repeat-outcome release](../experiments/evidence/website_repeat_outcomes_release_20260912.json) serves all six fresh results, fourteen replay windows, 1,056 captured frames, a 64/128 budget selector and immutable evidence links. Terra r2's continuation and both latest table outcomes are live. All thirteen older recordings and the stopped observer are unchanged. | Astra r2 is unlaunched because of the known native capacity shortage. No replay is invented for Sol's zero-call capacity failure. This release is not another game acceptance or independent trial. |
| Reviewed and merged remote implementation, tests, setup and manifests | Native code, website code and result manifests are pushed, with exact-revision tests and native/public evidence. Main is `f1aa05f429c189b67891cf2629e8e00329222aca`. | PR176 candidate `7acb4f72b254f9e9d41f7b0a3751f00b99d402cc` includes the comparison/viewer, portable owner and source image packager. Its two native ownership fixes passed 5,511 local tests, including 29 packaging tests; exact-head CI `34677562979` passed 5,367 tests with 154 skips. Hosted/local scopes differ. The unchanged viewer retains its earlier 51 Node contracts. [Native image/load acceptance](../experiments/evidence/keyboard_portable_native_load_acceptance_20260912.json) now passes, but full source review, actual owner/courier fresh-save-continuation and main merge remain. Public deployment is not merged harness delivery. |
| Reusable setup rather than one machine's retained experiment assets | The candidate installs in a fresh Python environment, loads three model configurations and reproduces the reports. Its base was imported into a separate clean local VM; the source-bound image then loaded a real seed and checkpoint under the configured unprivileged user. Original saves and contexts are unchanged. | The public owner supports fresh and unchanged continuation without a dated private owner, and reads all six original model checkpoints offline. The new image's two paused native loads verify startup and load compatibility, not a model-selected fresh run, creation/resume of its own new checkpoint, every Python protobuf observation/action path or portable-layout observer wiring. Verify those next with a short declared real-model acceptance. Do not redistribute restricted runtime images or private model data. |

## Integration started without changing active gameplay

The [new packaging result](../experiments/evidence/keyboard_portable_image_context_20260912.json)
verifies a real standalone source/binding context at that exact candidate:
952 files, 31,155,952 bytes, the original commit/tree, nine retained bindings and
a repeatable digest-bound check using exported code. No linked worktree or
alternate Git object store is needed. Ignored private inputs are excluded;
already-versioned fixture traces remain unchanged. The base image reference
comes from a historical inspection, not a new availability check. Both selected
local Docker endpoints were unreachable. No image build, game, VM or model
launch occurred. Native image construction and end-to-end acceptance remain open.

A [later export-only operation](../experiments/evidence/keyboard_portable_base_export_20260912.json)
reverified that base on the existing VM and exported it into private external
project storage. All 41 OCI objects and 35 uncompressed filesystem layers pass
digest verification; the exact index, image manifest and configuration identities
are retained separately. The first verifier's legacy-ID assumption failed and
was corrected in a separate offline verification, without reusing the operation.
The 361,589,248-byte archive is not a public distribution artifact. The existing
VM is stopped with its disk closed and its settings and Docker inventory unchanged.
There was no game, model, image build, new VM, disk resize or evidence deletion.
The original guest capacity shortage remains, so no frozen trial was consumed.
The standalone source context remains unchanged and passes its digest check.
Next import into a separately declared clean local runtime, build the source-bound
image and verify native fresh/continuation behavior. This export does not itself
prove import, source-image execution, native setup or gameplay acceptance.

The [following native setup acceptance](../experiments/evidence/keyboard_portable_native_load_acceptance_20260912.json)
now proves import into the separate clean VM, construction of the updated
source image and two paused native loads. The seed loads at year30/tick16801;
Astra r1's checkpoint64 loads at year30/tick39801. Both calendars, original
save inventories, configured container restrictions and native cleanup pass
the post-teardown audit. Both VMs are stopped and their data disks are closed.
The successful image contains exact source `7acb4f72b254f9e9d41f7b0a3751f00b99d402cc`
and is bound by ID `sha256:9bd47dc58da41bc5001d77c2bd67e6162ab7108e1f431e455b7e304338d0421d`.
It fixes two ownership assumptions exposed by actual builds/native copying,
retaining all failed setup identities and unchanged earlier source contexts.
No model call, requested game tick or new checkpoint occurred. Native-load
compatibility is now evidenced; the next proof is the portable owner's actual
model/courier fresh run followed by continuation from its own new save, with
resource bounds, token accounting, observer delivery and teardown. Do not
substitute repeated provider-free loads for that remaining end-to-end check.

The isolated `codex/year-two-integration` worktree starts at current remote main.
Merge `72f732546f1b6fa48a8074c582b8562f2592b92c` joins main's ancestry to frozen
native source `d22f28d99f4fd103188979e964e148139d3f3efd`. Its tree is
`2cf88a83406d01954de3ea1ad550caa293f87f2a`, exactly the native source tree;
all 5,056 Python tests passed, with ten skips. The difference is ancestry,
not a new gameplay implementation.

Eleven specific viewer commits through published website revision
`c763742f6e45d96c9b82df10a9776ee5bbbcb8fc` were then cherry-picked with source
provenance, retaining current main's campaign navigation. This excludes unrelated
historical benchmark-calibration and provider changes from the website branch.
The viewer slice passed 95 focused Python tests and all 48 Node contracts.
All eleven recording files remain byte-identical to their published sources.

The inherited-loss audit and rejected-choice observer changes are also integrated.
The observer helpers now match the current eleven-window viewer and shared
configured feed location. Sixty-one comparison, own-save, test and evidence files
were copied byte-for-byte from goal revision `727514096d8ec4fde22e4a0f47b5f7bf1bd5bd4e`.
The complete candidate passed 5,398 Python tests, with ten skips, and all 48 Node
contracts. Both website comparison tables match the integrated source reader.
The pushed candidate is [draft PR176](https://github.com/lemoz/fort-gym/pull/176),
head `5cedb5e91e0405e3b2ae0065c9a230a7ff02db88`; it is not merged or deployed.
Both the original native tree and combined candidate retain ten repository-wide
Ruff findings and 465 mypy errors in 27 files. Four historical evidence/test files retain trailing
blank lines. These pre-existing findings are not described as green checks.

The original candidate passed CI run `34666311317`. Terra's checkpoint128 and
published replay are integrated and pushed at `bce580ae30782b258453889283c10f1ccba06a7b`.
The updated candidate passes 5,420 Python tests and all 49 Node contracts; its
source reader reproduces both website tables. Updated-head CI `34667725373` passed.
The isolated Python/viewer setup has now passed at the same exact head:
installation, dependency checks, three model configurations, comparison/window
commands and twelve HTTP-served recordings. All 659 focused tests passed in its
fresh environment. The [additional source and setup review](../experiments/evidence/keyboard_integration_setup_review_176_20260912.json)
records its precise coverage. The local server was stopped; no game, model or VM
was launched for these checks. Generated bindings and fresh-machine native
provisioning remain unverified.

Next verify a short real Astra fresh/own-save run through the portable owner and
review the remaining combined source, and
merge only after that evidence exists. Preserve current main's work, all historical protocols and
results, and private-data exclusions. Never merge the whole conflicting
work-in-progress branch merely because its latest focused tests pass.

Terra and then Astra completed and their VMs stopped in declared order. Terra r2
subsequently completed from its original memory and zero-elapsed-time parent,
retaining 108,000 new ticks and 2,339,683 total tokens. Seven dwarves remain alive,
but no beds, workshops or farms are complete; food and drink stocks fell. Its
terminal audit, original-save preservation and VM teardown passed. The final
save has not had a separate fresh reload. Its replay and the latest comparison
outcomes are now verified live. Sol r2 hit the unchanged guest free-space floor before any
game or model call, with its parent intact and VM stopped. Astra r2 remains
unlaunched against that known shortage. No storage growth or evidence deletion
occurred; continue remaining source review and portable setup work within scope.

The frozen native checkout/image
and pinned observer remain isolated from integration. Finish the declared model sequence before unequal-length endurance
windows. Keep the full goal active until gameplay, comparison, setup, merged
source and public delivery requirements are all actually evidenced.
