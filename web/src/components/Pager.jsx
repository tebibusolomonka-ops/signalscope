/** "Showing 1 to 50 of 120" with previous and next buttons for a paged list. */
export function Pager({ offset, limit, count, total, onChange, emptyText = "Nothing found." }) {
  if (total === 0) return <p className="muted">{emptyText}</p>;
  return (
    <>
      <p className="muted">{`Showing ${offset + 1} to ${offset + count} of ${total}`}</p>
      <div className="form-row">
        <button
          type="button"
          className="secondary"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous page
        </button>
        <button
          type="button"
          className="secondary"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next page
        </button>
      </div>
    </>
  );
}
