"""Publish the audited displayed-key pilot separately from the older cohort."""

from .keyboard_endurance_records import read_result

RESULT_PATH = "experiments/evidence/keyboard_binding_astra_r1_20260911.json"
RESULT_SHA256 = "b016efeb037b321455cec9c0df6ea5e9e21553ca1e561730ed1bc3ed03b975ae"
RESULT_REVISION = "aae122e086b4254ed6865bb5886b307a576032a1"
SOURCE_REVISION = "8b9fffa1de4f93506cbcbdf82fd154aeb17b5697"
REPOSITORY = "https://github.com/lemoz/fort-gym/blob/"


def keyboard_binding_result() -> dict:
    result = read_result(RESULT_PATH, RESULT_SHA256)
    if (
        result["schema_version"] != "fortgym.public-keyboard-binding-trial-result/v1"
        or result["campaign_id"] != "bindings-20260911-astra-r1"
        or result["source_revision"] != SOURCE_REVISION
        or result["condition"]["same_condition_as_historical_matched_cohort"] is not False
        or result["audit"]["passed"] is not True
    ):
        raise ValueError("Unexpected displayed-key trial identity")
    return {
        "schema_version": "fortgym.public-keyboard-binding-results/v1",
        "recorded_only": True,
        "included_in_historical_cohort": False,
        "result_sha256": RESULT_SHA256,
        "result_url": REPOSITORY + RESULT_REVISION + "/" + RESULT_PATH,
        "condition_url": REPOSITORY + SOURCE_REVISION + "/" + result["condition"]["condition_path"],
        "trial_url": REPOSITORY + SOURCE_REVISION + "/" + result["condition"]["trial_path"],
        "result": result,
    }
