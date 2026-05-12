"use client";

import type { Endpoint } from "@/lib/types";

interface Props {
  endpoint: Endpoint;
  supplierName: string;
  view: "grid" | "list";
}

const CATEGORY_LABELS: Record<string, string> = {
  "ai-ml": "AI / ML",
  "language-models": "LLMs",
  "image-generation": "Images",
  "speech-audio": "Audio",
  "computer-vision": "Vision",
  "embeddings": "Embeddings",
  "finance": "Finance",
  "crypto-data": "Crypto",
  "market-data": "Markets",
  "data-analytics": "Data",
  "search": "Search",
  "web-scraping": "Scraping",
  "communication": "Comms",
  "location-maps": "Maps",
  "weather": "Weather",
  "commerce": "Commerce",
  "media-content": "Media",
  "security-identity": "Security",
  "developer-tools": "DevTools",
  "health-wellness": "Health",
  "travel-transport": "Travel",
};

function healthColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
}

function formatPrice(usdca: number): string {
  if (usdca < 1000) return `$${(usdca / 1_000_000).toFixed(6)}`;
  return `$${(usdca / 1_000_000).toFixed(4)}`;
}

export function MarketplaceCard({ endpoint, supplierName, view }: Props) {
  const categoryLabel = CATEGORY_LABELS[endpoint.category] ?? endpoint.category;
  const listingLabel = endpoint.listing_type?.toUpperCase() ?? "API";

  if (view === "list") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "14px 20px",
          backgroundColor: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          gap: "16px",
          transition: "border-color 0.15s, background-color 0.15s",
          cursor: "pointer",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(45,212,191,0.3)";
          (e.currentTarget as HTMLDivElement).style.backgroundColor = "var(--card-hover)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border)";
          (e.currentTarget as HTMLDivElement).style.backgroundColor = "var(--card)";
        }}
      >
        <span style={{
          fontSize: "11px", fontWeight: "600",
          padding: "3px 8px", borderRadius: "6px",
          backgroundColor: "var(--surface)", color: "var(--text-secondary)",
          border: "1px solid var(--border-subtle)", whiteSpace: "nowrap", flexShrink: 0,
        }}>
          {categoryLabel}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "2px" }}>
            <span style={{ fontSize: "14px", fontWeight: "600", color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {supplierName}
            </span>
            {endpoint.verified && (
              <span style={{ fontSize: "10px", color: "var(--accent)", flexShrink: 0 }}>✓</span>
            )}
          </div>
          {endpoint.description && (
            <p style={{ fontSize: "12px", color: "var(--text-muted)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {endpoint.description}
            </p>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "20px", flexShrink: 0 }}>
          <span style={{ fontSize: "13px", color: "var(--text-secondary)", fontFamily: "monospace" }}>
            {formatPrice(endpoint.min_price_usdca)}/req
          </span>
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
            ↑ {endpoint.rpm_limit} RPM
          </span>
          <span style={{ fontSize: "13px", fontWeight: "700", color: healthColor(endpoint.health_score) }}>
            {endpoint.health_score}
          </span>
          <span style={{ color: "var(--text-muted)", fontSize: "16px" }}>›</span>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        backgroundColor: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: "12px",
        padding: "20px",
        cursor: "pointer",
        transition: "border-color 0.15s, background-color 0.15s",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(45,212,191,0.3)";
        (e.currentTarget as HTMLDivElement).style.backgroundColor = "var(--card-hover)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border)";
        (e.currentTarget as HTMLDivElement).style.backgroundColor = "var(--card)";
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{
          fontSize: "11px", fontWeight: "600",
          padding: "3px 8px", borderRadius: "6px",
          backgroundColor: "var(--surface)", color: "var(--text-secondary)",
          border: "1px solid var(--border-subtle)",
        }}>
          {categoryLabel}
        </span>
        <span style={{
          fontSize: "10px", fontWeight: "700",
          padding: "3px 8px", borderRadius: "6px",
          backgroundColor: "rgba(45,212,191,0.08)",
          color: "var(--accent-light)",
          border: "1px solid rgba(45,212,191,0.15)",
          letterSpacing: "0.05em",
        }}>
          {listingLabel}
        </span>
      </div>

      <div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px" }}>
          <span style={{ fontSize: "15px", fontWeight: "700", color: "var(--text-primary)" }}>
            {supplierName}
          </span>
          {endpoint.verified && (
            <span style={{ fontSize: "11px", color: "var(--accent)" }} title="Verified">✓</span>
          )}
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ color: "var(--text-muted)", marginLeft: "auto" }}>
            <path d="M2 10L10 2M10 2H4M10 2v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        {endpoint.description ? (
          <p style={{
            fontSize: "13px", color: "var(--text-secondary)", margin: 0,
            lineHeight: "1.5", display: "-webkit-box",
            WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
          }}>
            {endpoint.description}
          </p>
        ) : (
          <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: 0, fontFamily: "monospace" }}>
            {endpoint.target_url}
          </p>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "16px", marginTop: "auto", paddingTop: "4px", borderTop: "1px solid var(--border-subtle)" }}>
        <span style={{ fontSize: "13px", color: "var(--text-secondary)", fontWeight: "600" }}>
          {formatPrice(endpoint.min_price_usdca)}
          <span style={{ fontSize: "11px", fontWeight: "400", color: "var(--text-muted)" }}>/req</span>
        </span>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "3px" }}>
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
            <path d="M6 1v2M6 9v2M1 6h2M9 6h2M2.5 2.5l1.5 1.5M8 8l1.5 1.5M2.5 9.5L4 8M8 4l1.5-1.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          {endpoint.rpm_limit} RPM
        </span>
        <span style={{ fontSize: "13px", fontWeight: "700", color: healthColor(endpoint.health_score), marginLeft: "auto" }}>
          {endpoint.health_score}
        </span>
      </div>
    </div>
  );
}
