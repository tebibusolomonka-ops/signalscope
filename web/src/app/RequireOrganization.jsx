import { Outlet } from "react-router";

import { PageHeading } from "../components/PageHeading.jsx";
import { Loading } from "../components/Status.jsx";
import { useOrganization } from "./useOrganization.js";

/**
 * Organization content pages need an active organization, system admins too:
 * there is no combined view and legacy content is not shown here.
 *
 * The pages are keyed by the organization, so switching unmounts them with
 * all their data before the new organization's pages load.
 */
export function RequireOrganization() {
  const { active, loading, error } = useOrganization();
  if (loading) return <Loading label="Loading organizations..." />;
  if (!active) {
    return (
      <>
        <PageHeading title="No organization selected" />
        <p>
          {error
            ? "Organizations could not be loaded, so no content can be shown."
            : "Content belongs to an organization. Choose one with the Active organization picker, or ask an organization owner for an invitation."}
        </p>
      </>
    );
  }
  return <Outlet key={active.id} />;
}
