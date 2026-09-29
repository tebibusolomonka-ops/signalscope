export function PageHeading({ title, children = null }) {
  return (
    <div className="page-heading">
      <h1>{title}</h1>
      {children}
    </div>
  );
}
