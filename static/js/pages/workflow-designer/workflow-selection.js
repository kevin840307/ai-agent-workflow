function allSystemWorkflows(systemWorkflow, state) {
  const systems = [systemWorkflow, ...(state.systemWorkflows || [])];
  const seen = new Set();
  return systems.filter((workflow) => {
    if (!workflow?.id || seen.has(workflow.id)) return false;
    seen.add(workflow.id);
    return true;
  });
}

function findWorkflowById(systemWorkflow, state, workflowId) {
  return allSystemWorkflows(systemWorkflow, state).find((workflow) => workflow.id === workflowId)
    || state.workflows.find((workflow) => workflow.id === workflowId)
    || null;
}

function isWorkflowReadOnly(workflow) {
  return Boolean(workflow?.kind === "system" || workflow?.protected || workflow?.deletable === false);
}

export { allSystemWorkflows, findWorkflowById, isWorkflowReadOnly };
