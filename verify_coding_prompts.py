#!/usr/bin/env python3
"""Verification script for coding track prompts."""

from prompts import build_stage_instructions, get_transition_ack, get_fallback_ack, CODE_EVALUATOR, QUESTION_GENERATION
from fsm import CodingStage

print("Testing build_stage_instructions for all CodingStage values:")
stages = [
    CodingStage.GREETING,
    CodingStage.SELF_INTRO,
    CodingStage.WARM_UP,
    CodingStage.CODING_PROBLEM_1,
    CodingStage.CODING_PROBLEM_2,
    CodingStage.CLOSING
]

for s in stages:
    result = build_stage_instructions(s)
    print(f'{s.value}: {len(result)} chars')

print("\nTesting get_transition_ack:")
for s in stages:
    result = get_transition_ack(s, "TestCandidate")
    print(f'{s.value}: "{result}"')

print("\nTesting get_fallback_ack:")
for s in stages:
    result = get_fallback_ack(s, "TestCandidate")
    print(f'{s.value}: "{result}"')

print("\nTesting CODE_EVALUATOR:")
print(f'CODE_EVALUATOR.system length: {len(CODE_EVALUATOR.system)}')
print(f'CODE_EVALUATOR.user_template length: {len(CODE_EVALUATOR.user_template)}')

print("\nTesting QUESTION_GENERATION.coding_system:")
print(f'QUESTION_GENERATION.coding_system length: {len(QUESTION_GENERATION.coding_system)}')

print("\nAll tests passed!")
