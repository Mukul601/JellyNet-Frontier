"use client";

import { useEffect, useState } from "react";
import { useSession, signIn } from "next-auth/react";
import { runTestCall, listProtocols, ApiError } from "@/lib/api";
import type { ProtocolPublic, TestCallResult } from "@/lib/types";
import { MainnetOverlay } from "@/components/NetworkBadge";
import { WalletSetupModal } from "@/components/WalletSetupModal";

export default function TestPage() {
  const { data: session, status, update: updateSession } = useSession();

  const [protocols, setProtocols] = useState<ProtocolPublic[]>([]);
  const [protocol, setProtocol] = useState("");
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("Hello, this is a test call from JellyNet");
  const [network, setNetwork] = useState<"testnet" | "mainnet">("testnet");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TestCallResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const token = (session as { backendToken?: string })?.backendToken ?? "";
  const isLoggedIn = status === "authenticated" && !!session;
  const needsWallet = isLoggedIn && !(session as { hasWallet?: boolean })?.hasWallet;

  useEffect(() => {
    listProtocols().then((list) => {
      setProtocols(list);
      if (list.length > 0 && !protocol) {
        const first = list[0];
        setProtocol(first.slug);
        const models = first.popular_models ? JSON.parse(first.popular_models) : [];
        if (models[0]) setModel(models[0]);
      }
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleProtocolChange(slug: string) {
    setProtocol(slug);
    const p = protocols.find((x) => x.slug === slug);
    if (p) {
      const models = p.popular_models ? JSON.parse(p.popular_models) : [];
      setModel(models[0] ?? "");
    }
    setResult(null);
    setError(null);
  }

  async function handleRun() {
    if (!isLoggedIn) {
      signIn("google", { callbackUrl: "/test" });
      return;
    }
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const res = await runTestCall({ protocol, model, prompt, network }, token);
      setResult(res);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 404) {
          setError("No supplier keys available for this protocol. Add one on the Dashboard.");
        } else if (e.status === 402) {
          setError("Insufficient credits. Top up in your profile.");
        } else {
          setError(e.message);
        }
      } else {
        setError(e instanceof Error ? e.message : "Test failed");
      }
    } finally {
      setRunning(false);
    }
  }

  if (status === "loading") return null;

  const selectedProto = protocols.find((p) => p.slug === protocol);
  const isLlmProtocol = selectedProto?.subcategory === "Language Models";

  return (
    <>
      <MainnetOverlay />
      {needsWallet && (
        <WalletSetupModal
          onComplete={async (address) => {
            await updateSession({ hasWallet: true, walletAddress: address });
          }}
          onDismiss={undefined}
        />
      )}

      <div style={{ maxWidth: "760px", margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ marginBottom: "32px" }}>
          <h1 style={{ fontSize: "26px", fontWeight: "700", marginBottom: "8px" }}>
            Test a Live API Call
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "14px", lineHeight: "1.6" }}>
            Pick a protocol, enter a prompt, and JellyNet will route it through a supplier key and return the response.
          </p>
        </div>

        {!isLoggedIn && (
          <div style={{ padding: "14px 18px", borderRadius: "10px", backgroundColor: "rgba(45,212,191,0.06)", border: "1px solid rgba(45,212,191,0.2)", marginBottom: "20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
            <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>Sign in to run live test calls.</span>
            <button
              onClick={() => signIn("google", { callbackUrl: "/test" })}
              style={{ padding: "8px 16px", borderRadius: "8px", background: "linear-gradient(135deg, #2dd4bf, #0d9488)", color: "white", border: "none", cursor: "pointer", fontWeight: "700", fontSize: "13px", whiteSpace: "nowrap" }}
            >
              Sign in →
            </button>
          </div>
        )}

        <div style={{ backgroundColor: "var(--card)", border: "1px solid var(--border)", borderRadius: "16px", padding: "28px", marginBottom: "20px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
            <div>
              <label style={labelStyle}>PROTOCOL</label>
              <select
                value={protocol}
                onChange={(e) => handleProtocolChange(e.target.value)}
                style={selectStyle}
              >
                {protocols.length === 0 && (
                  <option value="">Loading protocols…</option>
                )}
                {protocols.map((p) => (
                  <option key={p.slug} value={p.slug}>
                    {p.display_name}
                    {p.subcategory ? ` · ${p.subcategory}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>MODEL</label>
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                style={inputStyle}
                placeholder={isLlmProtocol ? "e.g. gpt-4o-mini" : "N/A for this protocol"}
                disabled={!isLlmProtocol && !!selectedProto}
              />
            </div>
          </div>

          {isLlmProtocol && (
            <div style={{ marginBottom: "16px" }}>
              <label style={labelStyle}>PROMPT</label>
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} style={{ ...inputStyle, resize: "vertical", lineHeight: "1.5" }} />
            </div>
          )}

          {!isLlmProtocol && selectedProto && (
            <div style={{ marginBottom: "16px", padding: "12px 16px", borderRadius: "8px", backgroundColor: "var(--surface)", border: "1px solid var(--border)", fontSize: "13px", color: "var(--text-muted)" }}>
              This protocol uses a fixed test payload defined in the catalog.
              {selectedProto.free_tier_note && (
                <span style={{ marginLeft: "8px", color: "var(--accent)" }}>
                  {selectedProto.free_tier_note}
                </span>
              )}
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", gap: "2px", padding: "3px", backgroundColor: "var(--surface)", borderRadius: "8px", border: "1px solid var(--border)" }}>
              {(["testnet", "mainnet"] as const).map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setNetwork(n)}
                  style={{
                    padding: "5px 14px",
                    fontSize: "11px",
                    fontWeight: "700",
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer",
                    letterSpacing: "0.06em",
                    backgroundColor: network === n
                      ? n === "testnet" ? "rgba(45,212,191,0.15)" : "rgba(249,115,22,0.15)"
                      : "transparent",
                    color: network === n
                      ? n === "testnet" ? "#2dd4bf" : "#f97316"
                      : "var(--text-muted)",
                  }}
                >
                  {n === "testnet" ? "TESTNET" : "MAINNET"}
                </button>
              ))}
            </div>

            <button
              onClick={handleRun}
              disabled={running || !protocol}
              style={{
                padding: "10px 24px",
                borderRadius: "10px",
                background: running ? "var(--border)" : "linear-gradient(135deg, #6366f1, #7c3aed)",
                color: "white",
                border: "none",
                cursor: running ? "not-allowed" : "pointer",
                fontWeight: "700",
                fontSize: "14px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
              }}
            >
              {running ? (
                <>
                  <span style={{ display: "inline-block", width: "13px", height: "13px", border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "white", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
                  Running…
                </>
              ) : (
                !isLoggedIn ? "Sign in to Run" : "▶ Run Test Call"
              )}
            </button>
          </div>
        </div>

        {error && (
          <div style={{ padding: "14px 18px", borderRadius: "10px", backgroundColor: "rgba(239,68,68,0.08)", border: "1px solid #ef4444", color: "#ef4444", fontSize: "14px", marginBottom: "20px" }}>
            {error}
          </div>
        )}

        {result && (
          <div style={{ backgroundColor: "var(--card)", border: "1px solid var(--border)", borderRadius: "16px", padding: "24px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
              <span style={{ padding: "3px 10px", borderRadius: "999px", backgroundColor: "rgba(45,212,191,0.12)", color: "#2dd4bf", fontSize: "11px", fontWeight: "700" }}>✓ SUCCESS</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>{result.protocol.toUpperCase()}</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>·</span>
              <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>{result.model}</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>·</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>{result.latency_ms}ms</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>·</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>{result.cost_micros}µUSDC</span>
              <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>·</span>
              <span style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "monospace" }}>key: {result.key_id_truncated}…</span>
            </div>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "16px" }}>
              <pre style={{ margin: 0, fontSize: "14px", color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: "1.6", fontFamily: "inherit" }}>
                {result.response}
              </pre>
            </div>
          </div>
        )}

        {!result && !error && (
          <div style={{ padding: "24px", borderRadius: "12px", border: "1px dashed var(--border)", color: "var(--text-muted)", fontSize: "13px", lineHeight: "1.7" }}>
            <div style={{ fontWeight: "600", marginBottom: "8px", color: "var(--text-secondary)" }}>How it works</div>
            <ol style={{ margin: 0, paddingLeft: "18px" }}>
              <li>Select a protocol and model above</li>
              <li>Enter a prompt — keep it short for faster results</li>
              <li>JellyNet picks an available supplier key from the pool</li>
              <li>The request is forwarded to the upstream API and the response returned here</li>
            </ol>
          </div>
        )}
      </div>
    </>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  fontWeight: "700",
  color: "var(--text-secondary)",
  letterSpacing: "0.08em",
  marginBottom: "7px",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 14px",
  borderRadius: "10px",
  border: "1px solid var(--border)",
  backgroundColor: "var(--surface)",
  color: "var(--text-primary)",
  fontSize: "14px",
  outline: "none",
  boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};
