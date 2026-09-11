# Failed attempts on the campaign page

The existing `/campaigns` page now shows the pre-save failure at trace boundary
695 separately from completed checkpoint 631. Its lead facts are 143,400 saved
ticks, 21,200 unsaved ticks and 711 accounted model responses. All 22,819,077
campaign tokens remain counted; subscription dollar charges stay unreported.

The failure stays in the same fortress history after its parent continuation.
It is not appended to the completed-continuation list. Unsaved population,
inventory and structure counts are available in a labelled details section.
The provider-free v4 save/reload acceptance appears as a follow-up inside the
failure, not as model progress or recovery of the lost tail. It does not imply
that gameplay has restarted.

The public adapter reads only the two explicitly allowlisted authored summaries.
It checks parent checkpoint identity, elapsed time, response/token arithmetic,
food coverage, diagnostic provenance and unchanged campaign counters. It never
projects raw game captures, model memory, prompts, runtime paths or arbitrary
fields. Missing or inconsistent evidence fails the public endpoint closed.

Validation includes projection/lineage mutation tests, the real JavaScript
renderer in the existing Node test harness, and HTTP checks against the actual
local FastAPI preview: `/campaigns`, the served scripts/styles and
`/public/keyboard-campaigns`. The served data matched the authored projection;
admin access remained disabled. These checks do not establish browser visual
acceptance, public deployment, live gameplay tracking or year-two success.

The Sites guidance was applied to preserve the existing Fort Labs architecture
and visual language, with a readable three-fact status block. No new hosted Site,
database migration, dependencies, social images or deployment was introduced.
