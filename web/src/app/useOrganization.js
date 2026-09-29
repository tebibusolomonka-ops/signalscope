import { createContext, useContext } from "react";

export const OrganizationContext = createContext(null);

export function useOrganization() {
  const value = useContext(OrganizationContext);
  if (value === null) {
    throw new Error("useOrganization must be used inside OrganizationProvider.");
  }
  return value;
}
