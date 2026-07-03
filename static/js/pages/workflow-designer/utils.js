import { ReviewModes, StepTypes } from "../workflow-designer-constants.js?v=20260703-wf-cli-config1";

function options(items, selected) {
  return items.map(([value, label]) => `
    <option value="${escapeAttr(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(label)}</option>
  `).join("");
}


function readInputValue(input) {
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") return Number(input.value || 0);
  return input.value;
}


function formatStepType(type) {
  return StepTypes.find(([value]) => value === type)?.[1] || type;
}


function formatReviewMode(mode) {
  return ReviewModes.find(([value]) => value === mode)?.[1] || mode;
}


function makeId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}


function clone(value) {
  return JSON.parse(JSON.stringify(value));
}


function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  })[char]);
}
function escapeAttr(value = "") {
  return escapeHtml(value);
}


function el(id) {
  return document.getElementById(id);
}


function on(id, event, handler) {
  const target = el(id);
  if (target) target.addEventListener(event, handler);
}


function setText(id, value) {
  const target = el(id);
  if (target) target.textContent = value;
}


function toast(message) {
  document.querySelectorAll(".designer-toast").forEach((node) => node.remove());
  const node = document.createElement("div");
  node.className = "designer-toast";
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2200);
}


async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}


export {
  options,
  readInputValue,
  formatStepType,
  formatReviewMode,
  makeId,
  clone,
  escapeHtml,
  escapeAttr,
  el,
  on,
  setText,
  toast,
  copyTextToClipboard
};
