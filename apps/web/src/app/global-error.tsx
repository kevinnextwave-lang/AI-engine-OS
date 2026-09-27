"use client";

/**
 * Last-resort boundary: replaces the ROOT layout when even it fails, so no
 * global CSS or fonts can be assumed — styles are inline on purpose.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "12px",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          background: "#fafafa",
          color: "#171717",
          padding: "24px",
          textAlign: "center",
        }}
      >
        <h1 style={{ fontSize: "20px", fontWeight: 600, margin: 0 }}>Something went wrong</h1>
        <p style={{ maxWidth: "28rem", fontSize: "14px", color: "#555", margin: 0 }}>
          The app hit an unexpected error{error.digest ? ` (ref ${error.digest})` : ""}. Your data
          is fine.
        </p>
        <button
          onClick={reset}
          style={{
            marginTop: "8px",
            padding: "8px 16px",
            borderRadius: "8px",
            border: "1px solid #d4d4d4",
            background: "#4f46e5",
            color: "#fff",
            fontSize: "14px",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
