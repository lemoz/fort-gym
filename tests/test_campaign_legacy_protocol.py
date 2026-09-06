"""Pin historical benchmark protocol from main 3a52860, not campaign strategy.

Changing these hashes is a protocol change, not a routine test update. These
checks exclude transport/accounting, whose separately documented changes are
deliberate. Formatting does not change the normalized syntax-tree hashes.
"""

import ast
import hashlib
import inspect
import json

import pytest

from fort_gym.bench.agent import governed_llm

PROMPTS = {
    "GOVERNED_SYSTEM_PROMPT": "7a846c083fdccf34410916aafa0261215adbb3c39bec3725c8699c69da899d71",
    "_GLM52_JSON_TRANSPORT_INSTRUCTION": "ea46f6adebe887129e8d6f81ef6adb10a7785bc41acbdc66cb2e4ae55d560742",
    "GOVERNED_OBSERVATION_PREAMBLE": "b9ebe4138609fd6c1803b035821a9d613d305d98f160fbc79d0f368ea9f71c01",
}
METHODS = {
    "_record_previous_outcome": "f1a2588b69badbb1ce5ce15f08357346b4cf09b8c7d88fb4e0e374a1cde4157c",
    "_apply_memory_fields": "b798f7e3cbb2477ae671f88f3a2bad753ad115bde157c287e347c8dfc201b9b2",
    "_normalize_payload": "129298ec7ca8addcdcb99c03f10297133420f875137cb7df921d7902e1f50940",
    "_normalize_redundant_plan_decision": "3ac5b3a6b404591445962bebd487cbddf561f399ad9ba4b04b3b980ebbc11419",
    "_review_contract_errors": "2ce3c2ee4f84cf16c298e63c67b4cb9b805f7b8bcedcdd48e50f26e4386b4150",
    "decide": "24d9ca9a008e1c8d5fa6e4753b35ee7e620bf37a2a8e0d93da5633512ad4ec65",
}


def canonical(node):
    if isinstance(node, ast.AST):
        return {
            "node": type(node).__name__,
            **{
                field: canonical(value)
                for field, value in ast.iter_fields(node)
                # Python 3.12 added this empty field to nongeneric functions.
                if not (field == "type_params" and not value)
            },
        }
    if isinstance(node, list):
        return [canonical(item) for item in node]
    return node


def digest(node):
    return hashlib.sha256(json.dumps(canonical(node), sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("name,expected", PROMPTS.items())
def test_historical_benchmark_prompt_is_unchanged(name, expected):
    assert hashlib.sha256(getattr(governed_llm, name).encode()).hexdigest() == expected


@pytest.mark.parametrize("name,expected", METHODS.items())
def test_historical_gameplay_decision_and_review_protocol_is_unchanged(name, expected):
    tree = ast.parse(inspect.getsource(governed_llm))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DFHackGovernedLLMAgent"
    )
    method = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    assert digest(method) == expected


def test_historical_tool_schema_is_unchanged():
    tree = ast.parse(inspect.getsource(governed_llm))
    tool = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_submit_action_tool"
    )
    assert digest(tool) == "cd373e9fcde8d5d26d82e888aa6bad27d86f0565b5dab820690751cf0f294697"
