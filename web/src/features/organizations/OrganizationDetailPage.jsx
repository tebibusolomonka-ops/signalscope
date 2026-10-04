import { useCallback } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";
import { Invitations } from "../invitations/Invitations.jsx";
import { AccessSummary } from "./AccessSummary.jsx";
import { Members } from "./Members.jsx";
import { Retention } from "./Retention.jsx";

export function OrganizationDetailPage() {
  const { organizationId } = useParams();
  const { api, user } = useAuth();
  const load = useCallback(async () => {
    const [organization, mine] = await Promise.all([
      api.get(`/organizations/${organizationId}`),
      api.get("/organizations"),
    ]);
    const role = mine.find((item) => item.organization.id === organizationId)?.role ?? null;
    return { organization, role };
  }, [api, organizationId]);
  const { data, error, loading } = useResource(load);

  if (loading) return <Loading />;
  if (error) {
    return (
      <>
        <PageHeading title="Organization" />
        <ErrorMessage error={error} />
      </>
    );
  }
  const { organization, role } = data;
  return (
    <>
      <PageHeading title={organization.name} />
      <dl className="panel">
        <dt>Slug</dt>
        <dd>{organization.slug}</dd>
        <dt>Your role</dt>
        <dd>{role ?? "Not a member (system admin access)"}</dd>
      </dl>
      {(role === "owner" || role === "admin" || role === null) && (
        <p>
          <Link to={`/organizations/${organizationId}/exports`}>Manage portable exports</Link>
        </p>
      )}
      {user?.is_system_admin && (
        <p>
          <Link to={`/organizations/${organizationId}/restore-plan`}>Plan a restore</Link>
        </p>
      )}
      <Members organizationId={organizationId} />
      <Invitations organizationId={organizationId} />
      <AccessSummary organizationId={organizationId} />
      <Retention organizationId={organizationId} />
    </>
  );
}
