import copy

import pytest

from fort_gym.bench.api import keyboard_cohort as cohort


@pytest.mark.parametrize("mutation", ["missing", "wrong_parent", "false_match", "boolean", "binding"])
def test_storage_changes_require_exact_declared_amendment(monkeypatch, mutation):
    original = cohort._read

    def altered(path, digest):
        result = original(path, digest)
        if result.get("campaign_id") == "matched-20260910-terra-r1":
            if mutation == "missing":
                result.pop("storage_amendment")
            elif mutation == "binding":
                result["execution"]["binding_sha256"] = cohort.ORIGINAL_BINDING
            elif mutation == "wrong_parent":
                result["storage_amendment"]["parent_execution_sha256"] = "a" * 64
            elif mutation == "false_match":
                result["storage_amendment"]["identical_host_configuration_to_first_two_trials"] = True
            else:
                result["storage_amendment"]["wall_clock_performance_comparison_excluded"] = 1
        return result

    monkeypatch.setattr(cohort, "_read", altered)
    with pytest.raises(ValueError):
        cohort.keyboard_cohort()


def test_amendment_cannot_be_backdated_to_original_trials():
    result = copy.deepcopy(cohort.keyboard_cohort()["trials"][0]["result"])
    result["execution"]["binding_sha256"] = cohort.STORAGE_BINDING
    result["storage_amendment"] = copy.deepcopy(cohort.STORAGE_AMENDMENT)
    with pytest.raises(ValueError):
        cohort._storage_condition(result, 0)
