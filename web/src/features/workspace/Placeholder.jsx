import { PageHeading } from "../../components/PageHeading.jsx";

/** A route whose workspace is not built yet. */
export function Placeholder({ title }) {
  return (
    <>
      <PageHeading title={title} />
      <p className="muted">This workspace is not available yet.</p>
    </>
  );
}
