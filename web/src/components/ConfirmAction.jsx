import { useEffect, useRef, useState } from "react";

import { ErrorMessage } from "./Status.jsx";

/**
 * A button that asks before it acts, inline instead of with window.confirm.
 *
 * The question gets focus, and Cancel returns to the first button.
 */
export function ConfirmAction({ label, question, confirmLabel, onConfirm }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const confirmRef = useRef(null);
  const openRef = useRef(null);
  const wasAsking = useRef(false);

  useEffect(() => {
    if (asking) confirmRef.current?.focus();
    else if (wasAsking.current) openRef.current?.focus();
    wasAsking.current = asking;
  }, [asking]);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  if (!asking) {
    return (
      <button type="button" className="danger" ref={openRef} onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <div role="group" aria-label={label} className="confirm">
      <p>{question}</p>
      <div className="form-row">
        <button type="button" className="danger" ref={confirmRef} disabled={busy} onClick={confirm}>
          {busy ? "Working..." : confirmLabel}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => setAsking(false)}
        >
          Cancel
        </button>
      </div>
      <ErrorMessage error={error} />
    </div>
  );
}
