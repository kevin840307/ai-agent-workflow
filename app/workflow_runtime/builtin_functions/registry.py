from __future__ import annotations

from app.workflow_runtime.builtin_functions.core import (
    adaptive_python_gate,
    require_status_pass,
    run_pytest,
    validate_general_auto_final,
    validate_general_auto_plan,
    validate_spec,
    validate_todo,
    collect_regression_context,
    generate_regression_case_doc,
    generate_regression_runtime_sql,
    generate_regression_sop_sql,
    generate_regression_validation,
    validate_regression_case_package,
)
from app.workflow_runtime.builtin_functions.security_context import collect_security_context
from app.workflow_runtime.builtin_functions.security_validation import (
    combine_security_candidates,
    finalize_security_report,
    generate_security_report,
    validate_security_candidates,
    validate_security_report,
)

PYTHON_FUNCTIONS = {
    "collect_security_context": collect_security_context,
    "combine_security_candidates": combine_security_candidates,
    "generate_security_report": generate_security_report,
    "finalize_security_report": finalize_security_report,
    "validate_security_candidates": validate_security_candidates,
    "validate_spec": validate_spec,
    "validate_todo": validate_todo,
    "require_status_pass": require_status_pass,
    "run_pytest": run_pytest,
    "adaptive_python_gate": adaptive_python_gate,
    "validate_general_auto_plan": validate_general_auto_plan,
    "validate_general_auto_final": validate_general_auto_final,
    "validate_security_report": validate_security_report,
    "collect_regression_context": collect_regression_context,
    "generate_regression_sop_sql": generate_regression_sop_sql,
    "generate_regression_runtime_sql": generate_regression_runtime_sql,
    "generate_regression_validation": generate_regression_validation,
    "generate_regression_case_doc": generate_regression_case_doc,
    "validate_regression_case_package": validate_regression_case_package,
}
