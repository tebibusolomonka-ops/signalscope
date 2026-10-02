import { useMemo, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { ErrorMessage } from "../../components/Status.jsx";
import { usePagedTenantOptions } from "../../lib/usePagedTenantOptions.js";

/**
 * Save a record in an open investigation of the active organization.
 *
 * Only open investigations of this organization are offered; the API checks
 * again that the record belongs to the investigation's organization.
 */
export function SaveToInvestigation({ itemType, referenceId }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button type="button" className="secondary" onClick={() => setOpen(true)}>
        Save to investigation
      </button>
    );
  }
  return <SaveForm itemType={itemType} referenceId={referenceId} onClose={() => setOpen(false)} />;
}

function SaveForm({ itemType, referenceId, onClose }) {
  const { tenantApi } = useOrganization();
  const filters = useMemo(() => ({ status: "open" }), []);
  const { items: investigations, error, loadMore, hasMore, loading, total } =
    usePagedTenantOptions("/investigations", filters);
  const [chosen, setChosen] = useState("");
  const [label, setLabel] = useState("");
  const [state, setState] = useState({ busy: false, error: null, saved: null });
  const selected = chosen || investigations[0]?.id || "";

  async function save(event) {
    event.preventDefault();
    setState({ busy: true, error: null, saved: null });
    const target = investigations.find((item) => item.id === selected);
    try {
      if (itemType === "research_session") {
        await tenantApi.post(`/investigations/${selected}/research-sessions/${referenceId}`);
      } else {
        const body = { item_type: itemType, reference_id: referenceId };
        if (label.trim()) body.label = label.trim();
        await tenantApi.post(`/investigations/${selected}/items`, body);
      }
      setState({ busy: false, error: null, saved: target });
    } catch (failure) {
      if (failure.status === 409 && failure.message.includes("already saved")) {
        setState({ busy: false, error: null, saved: { ...target, before: true } });
      } else {
        setState({ busy: false, error: failure, saved: null });
      }
    }
  }

  return (
    <form className="save-form" onSubmit={save} aria-label="Save to investigation">
      <ErrorMessage error={error} />
      {total === 0 && (
        <p className="muted">
          There is no open investigation in this organization.{" "}
          <Link to="/investigations">Start one</Link>
        </p>
      )}
      {investigations.length > 0 && (
        <div className="form-row">
          <label>
            Investigation
            <select value={selected} onChange={(event) => setChosen(event.target.value)}>
              {investigations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          {itemType !== "research_session" && (
            <label>
              Note (optional)
              <input maxLength={200} value={label} onChange={(e) => setLabel(e.target.value)} />
            </label>
          )}
          <button type="submit" disabled={state.busy}>
            {state.busy ? "Saving..." : "Save"}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          {hasMore && (
            <button type="button" className="secondary" onClick={loadMore} disabled={loading}>
              {loading ? "Loading..." : "Load more investigations"}
            </button>
          )}
        </div>
      )}
      <ErrorMessage error={state.error} />
      {state.saved && (
        <p role="status">
          {state.saved.before
            ? `Already saved in "${state.saved.title}".`
            : `Saved in "${state.saved.title}".`}{" "}
          <Link to={`/investigations/${state.saved.id}`}>Open the investigation</Link>
        </p>
      )}
    </form>
  );
}
