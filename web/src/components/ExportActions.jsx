import { useState } from "react";

import { useOrganization } from "../app/useOrganization.js";
import { downloadText, exportFileName } from "../lib/download.js";
import { ErrorMessage } from "./Status.jsx";

/**
 * Export buttons for a backend export route that answers JSON or Markdown.
 *
 * The files are the backend's exports as they are, built from saved
 * history; nothing is searched or answered again, and the Markdown is not
 * rewritten here.
 */
export function ExportActions({ path, kind, id }) {
  const { tenantApi } = useOrganization();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  async function run(name, work) {
    setBusy(name);
    setError(null);
    setCopied(false);
    try {
      await work();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(null);
    }
  }

  const markdown = () => tenantApi.getText(path, { query: { format: "markdown" } });

  return (
    <div className="form-row" role="group" aria-label="Export">
      <button
        type="button"
        className="secondary"
        disabled={busy !== null}
        onClick={() =>
          run("json", async () => {
            const data = await tenantApi.get(path, { query: { format: "json" } });
            const text = `${JSON.stringify(data, null, 2)}\n`;
            downloadText(exportFileName(kind, id, "json"), text, "application/json");
          })
        }
      >
        Export JSON
      </button>
      <button
        type="button"
        className="secondary"
        disabled={busy !== null}
        onClick={() =>
          run("markdown", async () => {
            downloadText(exportFileName(kind, id, "md"), await markdown(), "text/markdown");
          })
        }
      >
        Export Markdown
      </button>
      {navigator.clipboard && (
        <button
          type="button"
          className="secondary"
          disabled={busy !== null}
          onClick={() =>
            run("copy", async () => {
              await navigator.clipboard.writeText(await markdown());
              setCopied(true);
            })
          }
        >
          Copy Markdown
        </button>
      )}
      {busy && <span role="status">Preparing export...</span>}
      {copied && <span role="status">Markdown copied.</span>}
      <ErrorMessage error={error} />
    </div>
  );
}
