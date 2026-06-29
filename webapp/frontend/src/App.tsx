import { useState } from "react";
import { CunninghamProvider } from "@gouvfr-lasuite/ui-kit";
import { Button, Input, Loader } from "@gouvfr-lasuite/cunningham-react";
import "@gouvfr-lasuite/ui-kit/style";
import "./App.scss";

function ExportApp() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleExport = async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setDone(false);

    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `Server error ${res.status}`);
      }

      const disposition = res.headers.get("Content-Disposition") || "";
      const nameMatch = disposition.match(/filename="?([^"]+)"?/);
      const filename = nameMatch ? nameMatch[1] : "docs-export.zip";

      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      setDone(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleExport();
  };

  return (
    <div className="export-page">
      <main className="export-card">
        <div className="export-card__header">
          <h1 className="export-card__title">Docs Export</h1>
          <p className="export-card__subtitle">
            Download any public LaSuite Docs document tree as a zip of markdown
            files.
          </p>
        </div>

        <div className="export-card__warning" role="alert">
          <span className="export-card__warning-icon">⚠️</span>
          <span>
            This tool only works with <strong>public</strong> documents. Private
            or restricted docs will return an error.
          </span>
        </div>

        <div className="export-card__form">
          <Input
            label="Document URL"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setDone(false);
              setError(null);
            }}
            onKeyDown={handleKeyDown}
            placeholder="https://docs.numerique.gouv.fr/docs/..."
            fullWidth
            disabled={loading}
          />

          <Button
            onClick={handleExport}
            disabled={loading || !url.trim()}
            fullWidth
          >
            {loading ? "Exporting…" : "Export as .zip"}
          </Button>
        </div>

        {loading && (
          <div className="export-card__loader">
            <Loader aria-label="Export in progress" />
            <p>Fetching all pages and media — this may take a few minutes for large docs.</p>
          </div>
        )}

        {error && (
          <div className="export-card__error" role="alert">
            <strong>Error:</strong> {error}
          </div>
        )}

        {done && !error && (
          <div className="export-card__success" role="status">
            ✅ Download started!
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <CunninghamProvider>
      <ExportApp />
    </CunninghamProvider>
  );
}
