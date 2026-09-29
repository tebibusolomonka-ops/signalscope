import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { ITEM_TYPES, describeItem } from "./items.js";

/**
 * One investigation of the active organization with its saved items.
 *
 * An investigation of another organization is treated as not found here,
 * even when the user may view it, so it only appears under its own
 * organization.
 */
export function InvestigationDetailPage() {
  const { investigationId } = useParams();
  const { active, tenantApi } = useOrganization();
  const load = useCallback(async () => {
    const investigation = await tenantApi.get(`/investigations/${investigationId}`);
    if (investigation.organization_id !== active.id) return { elsewhere: true };
    const items = await tenantApi.get(`/investigations/${investigationId}/items`);
    return { investigation, items };
  }, [tenantApi, investigationId, active.id]);
  const { data, error, loading, reload } = useResource(load);
  // A status change answers with the changed investigation.
  const [changed, setChanged] = useState(null);
  const investigation = changed ?? data?.investigation;

  return (
    <>
      <PageHeading title={investigation ? investigation.title : "Investigation"}>
        <Link to="/investigations">All investigations</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data?.elsewhere && (
        <p className="error" role="alert">
          This investigation does not belong to the active organization.
        </p>
      )}
      {investigation && (
        <>
          <Overview investigation={investigation} onChange={setChanged} />
          <Items investigation={investigation} items={data.items} onChange={reload} />
        </>
      )}
    </>
  );
}

function Overview({ investigation, onChange }) {
  const { tenantApi } = useOrganization();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const closed = investigation.status === "closed";

  async function setStatus(status) {
    setBusy(true);
    setError(null);
    try {
      onChange(await tenantApi.patch(`/investigations/${investigation.id}`, { status }));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await tenantApi.delete(`/investigations/${investigation.id}`);
    navigate("/investigations");
  }

  return (
    <section className="panel" aria-labelledby="investigation-overview">
      <h2 id="investigation-overview">Overview</h2>
      {closed && (
        <p className="notice" role="note">
          This investigation is closed and read only. Reopen it to change it.
        </p>
      )}
      <dl className="facts">
        <dt>Status</dt>
        <dd>{investigation.status}</dd>
        <dt>Description</dt>
        <dd>{investigation.description ?? "-"}</dd>
        <dt>Created</dt>
        <dd>{formatTime(investigation.created_at)}</dd>
        <dt>Updated</dt>
        <dd>{formatTime(investigation.updated_at)}</dd>
      </dl>
      <div className="form-row actions">
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => setStatus(closed ? "open" : "closed")}
        >
          {closed ? "Reopen" : "Close"}
        </button>
        {!closed && (
          <ConfirmAction
            label="Delete investigation"
            question="Delete this investigation and its saved items? The saved records stay."
            confirmLabel="Yes, delete investigation"
            onConfirm={remove}
          />
        )}
      </div>
      <ErrorMessage error={error} />
    </section>
  );
}

function Items({ items }) {
  return (
    <section className="panel" aria-labelledby="investigation-items">
      <h2 id="investigation-items">Saved items</h2>
      <p className="muted">Each item shows the record as it was when it was saved.</p>
      {items.length === 0 && <p className="muted">Nothing is saved yet.</p>}
      {ITEM_TYPES.map(([type, heading]) => {
        const group = items.filter((item) => item.item_type === type);
        if (group.length === 0) return null;
        return (
          <section key={type} aria-label={heading}>
            <h3>{heading}</h3>
            <ul className="items">
              {group.map((item) => (
                <SavedItem key={item.id} item={item} />
              ))}
            </ul>
          </section>
        );
      })}
    </section>
  );
}

function SavedItem({ item }) {
  const { title, detail, href } = describeItem(item);
  return (
    <li>
      {href ? <Link to={href}>{title}</Link> : <span>{title}</span>}
      <span className="muted">{` (${detail}; saved ${formatTime(item.created_at)})`}</span>
      {item.label && <p className="label">{item.label}</p>}
    </li>
  );
}
