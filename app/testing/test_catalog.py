from __future__ import annotations

from pathlib import Path

PYTEST_GROUPS: list[tuple[str, list[str]]] = [
    (
        "A_core_cli_api",
        [
            "tests/test_agent_execution_service.py",
            "tests/test_agent_runner.py",
            "tests/test_ai_workflow_assets_ui.py",
            "tests/test_aiwf_cli.py",
            "tests/test_api_smoke.py",
            "tests/test_auto_workflow_orchestrator.py",
            "tests/test_controller_observability_and_manual_controls.py",
            "tests/test_controller_productization.py",
        ],
    ),
    (
        "B_general_project_prompt",
        [
            "tests/test_general_auto_development_workflow.py",
            "tests/test_isolated_workspace.py",
            "tests/test_large_project_fixture.py",
            "tests/test_project_and_config_api.py",
            "tests/test_prompt_builder.py",
            "tests/test_python_functions_multi.py",
        ],
    ),
    (
        "C_productization_features",
        [
            "tests/test_next_round_features.py",
            "tests/test_practical_platform_features.py",
            "tests/test_test_pipeline_and_lifecycle.py",
            "tests/test_productization_next_features.py",
        ],
    ),
    (
        "D_manual_run_state",
        [
            "tests/test_real_qwen_workflow_manual.py",
            "tests/test_release_and_ui_manual.py",
            "tests/test_real_qwen_unattended_manual.py",
            "tests/test_run_state.py",
        ],
    ),
    (
        "E_runtime_safety_contracts",
        [
            "tests/test_runtime_files_and_qwen.py",
            "tests/test_runtime_refactor_contract.py",
            "tests/test_runtime_safety.py",
            "tests/test_static_architecture_contract.py",
            "tests/test_supervisor_patch_defaults_and_action_split.py",
            "tests/test_hardening_next.py",
            "tests/test_production_hardening_round2.py",
            "tests/test_production_hardening_round3.py",
            "tests/test_project_path_write_mode.py",
            "tests/test_full_system_optimization_round4.py",
            "tests/test_reliability_hardening_round5.py",
            "tests/test_workflow_optimization_v6.py",
            "tests/test_workflow_optimization_v7.py",
            "tests/test_system_optimization_v8.py",
            "tests/test_system_productization_v9.py",
            "tests/test_production_readiness_v10.py",
            "tests/test_stability_v11.py",
            "tests/test_stability_completion_v15.py",
            "tests/test_unattended_stability_v16.py",
            "tests/test_v17_runtime_ui_regressions.py",
            "tests/test_reliability_v18.py",
            "tests/test_ui_and_local_qwen_v12.py",
            "tests/test_unattended_v20.py",
            "tests/test_v21_patch_review_artifacts.py",
            "tests/test_v22_artifact_diff_step_preview.py",
            "tests/test_v23_release_failure_runtime.py",
            "tests/test_v24_stability_convergence.py",
            "tests/test_v24_security_scan_hotfix.py",
            "tests/test_real_qwen_unattended_e2e_contract.py",
        ],
    ),
    (
        "F_workflow_assets_stability",
        [
            "tests/test_workflow_advanced_stability.py",
            "tests/test_workflow_assets.py",
            "tests/test_workflow_assets_functional_e2e.py",
            "tests/test_workflow_config_service.py",
        ],
    ),
    ("G_self_prompt_e2e", ["tests/test_self_prompt_workflow_e2e.py"]),
    (
        "H_workflow_core_contracts",
        [
            "tests/test_workflow_core.py",
            "tests/test_workflow_function_refactor_contract.py",
            "tests/test_workflow_functions.py",
        ],
    ),
    ("I_workflow_integration", ["tests/test_workflow_integration.py"]),
    (
        "J_workflow_quality_resilience",
        [
            "tests/test_workflow_non_e2e_contracts.py",
            "tests/test_workflow_quality_contracts.py",
            "tests/test_workflow_resilience_e2e.py",
        ],
    ),
]

FAST_GROUPS = {"A_core_cli_api", "B_general_project_prompt", "C_productization_features", "D_manual_run_state"}
E2E_GROUPS = {
    "E_runtime_safety_contracts",
    "F_workflow_assets_stability",
    "G_self_prompt_e2e",
    "H_workflow_core_contracts",
    "I_workflow_integration",
    "J_workflow_quality_resilience",
}

TEST_TIERS: dict[str, set[str]] = {
    "unit": {"A_core_cli_api", "B_general_project_prompt"},
    "contract": {"C_productization_features", "E_runtime_safety_contracts", "H_workflow_core_contracts"},
    "integration": {"D_manual_run_state", "F_workflow_assets_stability", "I_workflow_integration"},
    "e2e": {"G_self_prompt_e2e", "J_workflow_quality_resilience"},
    "soak": {"G_self_prompt_e2e"},
}


PROFILE_TIERS: dict[str, set[str]] = {
    "developer": {"unit"},
    "commit": {"unit", "contract"},
    "release": {"unit", "contract", "integration", "e2e"},
    "e2e": {"e2e"},
}


def group_for_test_file(path: str | Path) -> str | None:
    normalized = Path(path).as_posix()
    if not normalized.startswith("tests/"):
        normalized = f"tests/{Path(normalized).name}"
    for group_name, files in PYTEST_GROUPS:
        if normalized in files:
            return group_name
    return None


def tier_for_group(group_name: str) -> str:
    for tier in ("unit", "contract", "integration", "e2e", "soak"):
        if group_name in TEST_TIERS.get(tier, set()):
            return tier
    return "integration"


def markers_for_test_file(path: str | Path) -> set[str]:
    name = Path(path).name.lower()
    group = group_for_test_file(path)
    markers: set[str] = set()
    if name.endswith("_manual.py") or name == "test_release_and_ui_manual.py":
        markers.add("manual")
        if "real_qwen" in name or "real_agent" in name:
            markers.add("real_agent")
        return markers
    if group:
        markers.add(tier_for_group(group))
    else:
        markers.add("integration")
    return markers


def groups_for_profile(profile: str) -> list[tuple[str, list[str]]]:
    tiers = PROFILE_TIERS.get(profile)
    if tiers is None:
        raise ValueError(f"Unknown test profile: {profile}")
    names: set[str] = set()
    for tier in tiers:
        names.update(TEST_TIERS.get(tier, set()))
    return [(name, files) for name, files in PYTEST_GROUPS if name in names]


__all__ = [
    "E2E_GROUPS",
    "FAST_GROUPS",
    "PROFILE_TIERS",
    "PYTEST_GROUPS",
    "TEST_TIERS",
    "group_for_test_file",
    "groups_for_profile",
    "markers_for_test_file",
    "tier_for_group",
]
