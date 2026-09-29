/** The DOM id of an evidence card, so a citation can find it. */
export function evidenceElementId(scope, evidenceId) {
  return `evidence-${scope}-${evidenceId}`;
}

/** Move focus to an evidence card, if it is on the page. */
export function focusEvidence(scope, evidenceId) {
  const card = document.getElementById(evidenceElementId(scope, evidenceId));
  if (!card) return;
  card.focus();
  card.scrollIntoView?.({ block: "nearest" });
}
