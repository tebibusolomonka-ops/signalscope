export function Loading({ label = "Loading..." }) {
  return <p role="status">{label}</p>;
}

export function ErrorMessage({ error }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error.message}
    </p>
  );
}
