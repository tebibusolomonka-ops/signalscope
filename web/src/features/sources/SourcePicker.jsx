export function SourcePicker({ options, label = "Source", name = "source_id", defaultValue = "" }) {
  const { sources, query, setQuery, loadMore, hasMore, loading, error } = options;
  return (
    <fieldset className="picker">
      <legend>{label}</legend>
      <label>
        Find source
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <label>
        {label}
        <select name={name} defaultValue={defaultValue}>
          <option value="">All sources</option>
          {sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.name}
            </option>
          ))}
        </select>
      </label>
      {hasMore && (
        <button type="button" className="secondary" onClick={loadMore} disabled={loading}>
          {loading ? "Loading..." : "Load more sources"}
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
    </fieldset>
  );
}
