import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

export function OrganizationsPage() {
  const { api } = useAuth();
  const load = useCallback(() => api.get("/organizations"), [api]);
  const { data, error, loading, reload } = useResource(load);

  return (
    <>
      <PageHeading title="Organizations" />
      <section className="panel" aria-labelledby="my-organizations">
        <h2 id="my-organizations">Your organizations</h2>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.length === 0 && <p className="muted">You are not in any organization yet.</p>}
        {data && data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Slug</th>
                <th scope="col">Your role</th>
              </tr>
            </thead>
            <tbody>
              {data.map(({ organization, role }) => (
                <tr key={organization.id}>
                  <td>
                    <Link to={`/organizations/${organization.id}`}>{organization.name}</Link>
                  </td>
                  <td>{organization.slug}</td>
                  <td>{role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <CreateOrganization onCreated={reload} />
    </>
  );
}

function CreateOrganization({ onCreated }) {
  const { api } = useAuth();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/organizations", { name, slug });
      setName("");
      setSlug("");
      onCreated();
    } catch (failure) {
      setError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-organization">
      <h2 id="create-organization">Create an organization</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Name
          <input required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Slug
          <input required value={slug} onChange={(event) => setSlug(event.target.value)} />
        </label>
        <ErrorMessage error={error} />
        <button type="submit">Create</button>
      </form>
    </section>
  );
}
