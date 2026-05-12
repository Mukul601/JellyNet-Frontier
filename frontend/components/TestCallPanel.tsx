"use client";

import type { TestRunResult } from "@/lib/types";
import { getExplorerTxUrl } from "@/lib/chain-utils";

interface Props {
  result: TestRunResult;
}

const STATUS_ICON: Record<string, string> = {
  done: "✓",
  error: "✗",
  running: "◌",
  pending: "○",
};

const STATUS_COLOR: Record<string, string> = {
  done: "var(--success)",
  error: "var(--error)",
  running: "var(--accent-light)",
  pending: "var(--text-muted)",
};

export function TestCallPanel({ result }: Props) {
  return (
    <div style={{ animation: "fade-in 0.3s ease-out" }}>
      <div
        style={{
          backgroundColor: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "16px",
          padding: "28px",
          marginBottom: "16px",
        }}
      >
        <h3
          style={{
            fontSize: "15px",
            fontWeight: "700",
            marginBottom: "20px",
            color: "var(--text-secondary)",
            letterSpacing: "0.05em",
          }}
        >
          EXECUTION STEPS
        </h3>

        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
          {result.steps.map((step, i) => (
            <div
              key={step.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "12px",
                padding: "10px 0",
                borderBottom:
                  i < result.steps.length - 1
                    ? "1px solid var(--border-subtle)"
                    : "none",
              }}
            >
              <div
                style={{
                  width: "22px",
                  height: "22px",
                  borderRadius: "50%",
                  backgroundColor:
                    step.status === "done"
                      ? "var(--success-dim)"
                      : step.status === "error"
                      ? "var(--error-dim)"
                      : step.status === "running"
                      ? "var(--accent-glow)"
                      : "var(--surface)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "11px",
                  fontWeight: "700",
                  color: STATUS_COLOR[step.status],
                  flexShrink: 0,
                  marginTop: "1px",
                  animation:
                    step.status === "running" ? "pulse-glow 1.5s infinite" : "",
                }}
              >
                {STATUS_ICON[step.status]}
              </div>

              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontSize: "14px",
                    color:
                      step.status === "error"
                        ? "var(--error)"
                        : "var(--text-primary)",
                    fontWeight: step.status === "done" ? "500" : "400",
                  }}
                >
                  {step.label}
                </div>
                {step.detail && (
                  <div
                    style={{
                      fontSize: "12px",
                      color: "var(--text-muted)",
                      marginTop: "3px",
                      fontFamily: "monospace",
                    }}
                  >
                    {step.detail}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {result.tx_hash && result.success && (
        <div
          style={{
            backgroundColor: "var(--success-dim)",
            border: "1px solid var(--success)",
            borderRadius: "12px",
            padding: "16px 20px",
            marginBottom: "16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ color: "var(--success)", fontSize: "18px" }}>✓</span>
            <div>
              <div
                style={{
                  fontSize: "14px",
                  fontWeight: "700",
                  color: "var(--success)",
                }}
              >
                Payment Confirmed On-Chain
              </div>
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--text-muted)",
                  fontFamily: "monospace",
                  marginTop: "2px",
                }}
              >
                {result.tx_hash.slice(0, 16)}...{result.tx_hash.slice(-8)}
              </div>
            </div>
          </div>
          {result.explorer_url && (
            <a
              href={result.explorer_url}
              target="_blank"
              rel="noreferrer"
              style={{
                padding: "7px 16px",
                borderRadius: "8px",
                backgroundColor: "rgba(34, 197, 94, 0.15)",
                color: "var(--success)",
                fontSize: "13px",
                fontWeight: "600",
                textDecoration: "none",
                border: "1px solid rgba(34, 197, 94, 0.3)",
              }}
            >
              View on Explorer ↗
            </a>
          )}
        </div>
      )}

      {result.upstream_response && (
        <div
          style={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "16px",
            padding: "24px",
          }}
        >
          <div
            style={{
              fontSize: "12px",
              fontWeight: "700",
              color: "var(--text-muted)",
              letterSpacing: "0.08em",
              marginBottom: "14px",
            }}
          >
            UPSTREAM API RESPONSE
          </div>
          <pre
            style={{
              fontSize: "12px",
              color: "var(--text-secondary)",
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "8px",
              padding: "16px",
              overflow: "auto",
              maxHeight: "360px",
              margin: 0,
              fontFamily: "monospace",
              lineHeight: "1.6",
            }}
          >
            {JSON.stringify(result.upstream_response, null, 2)}
          </pre>
        </div>
      )}

      {result.error && !result.success && (
        <div
          style={{
            backgroundColor: "var(--error-dim)",
            border: "1px solid var(--error)",
            borderRadius: "12px",
            padding: "16px 20px",
            color: "var(--error)",
            fontSize: "14px",
          }}
        >
          <strong>Error:</strong> {result.error}
        </div>
      )}
    </div>
  );
}
