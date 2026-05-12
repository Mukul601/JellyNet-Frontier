"use client";

import { useState, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { useSession } from "next-auth/react";
import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { PublicKey } from "@solana/web3.js";

interface Props {
  onComplete: (address: string) => void;
  onDismiss?: () => void;
  currentWalletAddress?: string;
}

function isValidSolanaAddress(input: string): boolean {
  try {
    const key = new PublicKey(input);
    return key.toBytes().length === 32;
  } catch {
    return false;
  }
}

export function WalletSetupModal({ onComplete, onDismiss, currentWalletAddress }: Props) {
  const { data: session } = useSession();
  const { publicKey, connected, disconnect } = useWallet();
  const [error, setError] = useState("");
  const [connectLoading, setConnectLoading] = useState(false);
  const [addressInput, setAddressInput] = useState("");
  const [showConfirmReplace, setShowConfirmReplace] = useState(false);
  const [pendingAddress, setPendingAddress] = useState<string | null>(null);
  const [adapterOpen, setAdapterOpen] = useState(false);

  const token = session?.backendToken;
  const hasExistingWallet = session?.hasWallet;

  useEffect(() => {
    if (connected && publicKey) {
      setAdapterOpen(false);
      const address = publicKey.toBase58();
      handleSubmit(address);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, publicKey]);

  useEffect(() => {
    if (!adapterOpen) return;
    function onFocus() { if (!connected) setAdapterOpen(false); }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [adapterOpen, connected]);

  const submitAddress = useCallback(
    async (address: string) => {
      if (!token) return;
      setConnectLoading(true);
      setError("");
      try {
        const res = await fetch("/api/auth/wallet/connect", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ address }),
        });
        if (!res.ok) {
          let detail = "Failed to save wallet address";
          try {
            const d = await res.json();
            detail = d.detail ?? detail;
          } catch {}
          if (res.status === 502 || res.status === 503 || res.status === 504) {
            detail = "Backend unavailable. Make sure the server is running.";
          }
          throw new Error(detail);
        }
        if (connected) disconnect();
        onComplete(address);
      } catch (e: unknown) {
        if (e instanceof TypeError && e.message.includes("fetch")) {
          setError("Cannot reach the backend. Check that the server is running.");
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setConnectLoading(false);
        setPendingAddress(null);
        setShowConfirmReplace(false);
      }
    },
    [token, onComplete, connected, disconnect]
  );

  function handleSubmit(address: string) {
    if (!isValidSolanaAddress(address)) {
      setError("Invalid Solana address — must be a valid base58 public key.");
      return;
    }
    if (hasExistingWallet) {
      setPendingAddress(address);
      setShowConfirmReplace(true);
      return;
    }
    submitAddress(address);
  }

  function handleManualSubmit() {
    const address = addressInput.trim();
    handleSubmit(address);
  }

  function handleConfirmReplace() {
    if (pendingAddress) submitAddress(pendingAddress);
  }

  function handleCancelReplace() {
    setPendingAddress(null);
    setShowConfirmReplace(false);
    if (connected) disconnect();
  }

  const modal = (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0,0,0,0.75)",
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "16px",
        visibility: adapterOpen ? "hidden" : "visible",
        pointerEvents: adapterOpen ? "none" : "auto",
      }}
      onClick={onDismiss}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "20px",
          padding: "36px 32px",
          maxWidth: "480px",
          width: "100%",
          animation: "fade-in 0.3s ease-out",
          position: "relative",
          maxHeight: "90vh",
          overflow: "visible",
        }}
      >
        {onDismiss && (
          <button
            onClick={onDismiss}
            aria-label="Close"
            style={{
              position: "absolute",
              top: "16px",
              right: "16px",
              width: "32px",
              height: "32px",
              borderRadius: "50%",
              border: "1px solid var(--border)",
              backgroundColor: "var(--surface)",
              color: "var(--text-muted)",
              fontSize: "18px",
              lineHeight: 1,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ×
          </button>
        )}

        <h2 style={{ fontSize: "20px", fontWeight: "700", marginBottom: "6px", color: "var(--text-primary)" }}>
          Connect Withdrawal Wallet
        </h2>
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "28px", lineHeight: "1.6" }}>
          Optional — only needed to withdraw earnings. You can skip this and set it up later.
        </p>

        {showConfirmReplace && (
          <div
            style={{
              padding: "16px",
              borderRadius: "12px",
              backgroundColor: "rgba(245,158,11,0.06)",
              border: "1px solid rgba(245,158,11,0.3)",
              marginBottom: "20px",
            }}
          >
            <p style={{ fontSize: "13px", color: "#f59e0b", fontWeight: "600", marginBottom: "8px" }}>
              Replace your current wallet?
            </p>
            {currentWalletAddress && (
              <p style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "monospace", marginBottom: "8px", wordBreak: "break-all" }}>
                Current: {currentWalletAddress.slice(0, 12)}…{currentWalletAddress.slice(-8)}
              </p>
            )}
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "16px", lineHeight: "1.6" }}>
              This will replace your current withdrawal wallet. Any pending earnings will still be paid to the old address until the next epoch closes.
            </p>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                onClick={handleConfirmReplace}
                disabled={connectLoading}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: "8px",
                  background: "linear-gradient(135deg, var(--accent), #0d9488)",
                  color: "#060b0f",
                  fontWeight: "600",
                  fontSize: "13px",
                  border: "none",
                  cursor: connectLoading ? "not-allowed" : "pointer",
                  opacity: connectLoading ? 0.7 : 1,
                }}
              >
                {connectLoading ? "Saving…" : "Yes, replace wallet"}
              </button>
              <button
                onClick={handleCancelReplace}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: "8px",
                  background: "var(--surface)",
                  color: "var(--text-secondary)",
                  fontWeight: "600",
                  fontSize: "13px",
                  border: "1px solid var(--border)",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {!showConfirmReplace && (
          <>
            <div
              style={{ marginBottom: "20px", display: "flex", flexDirection: "column", alignItems: "center" }}
              onClick={() => { if (!connected) setAdapterOpen(true); }}
            >
              <WalletMultiButton
                style={{
                  width: "100%",
                  justifyContent: "center",
                  borderRadius: "10px",
                  fontSize: "15px",
                  fontWeight: "600",
                  height: "48px",
                  backgroundColor: connected ? "rgba(45,212,191,0.15)" : undefined,
                }}
              />
              {connected && publicKey && (
                <p style={{ fontSize: "11px", color: "var(--accent)", marginTop: "8px", fontFamily: "monospace", textAlign: "center" }}>
                  ✓ {publicKey.toBase58().slice(0, 12)}…{publicKey.toBase58().slice(-8)} — saving…
                </p>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "20px" }}>
              <div style={{ flex: 1, height: "1px", backgroundColor: "var(--border-subtle)" }} />
              <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>or enter manually</span>
              <div style={{ flex: 1, height: "1px", backgroundColor: "var(--border-subtle)" }} />
            </div>

            <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "10px", lineHeight: "1.6" }}>
              Enter your Solana public key. Only the address is stored — used to send withdrawal payments.
            </p>
            <input
              type="text"
              value={addressInput}
              onChange={(e) => { setAddressInput(e.target.value); setError(""); }}
              placeholder="Solana public key (base58)"
              autoComplete="off"
              spellCheck={false}
              style={{
                width: "100%",
                padding: "12px 14px",
                borderRadius: "10px",
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
                fontSize: "13px",
                fontFamily: "monospace",
                marginBottom: "12px",
                outline: "none",
                boxSizing: "border-box",
              }}
            />
            <button
              onClick={handleManualSubmit}
              disabled={connectLoading || !isValidSolanaAddress(addressInput.trim())}
              style={{
                width: "100%",
                padding: "13px",
                borderRadius: "10px",
                background: isValidSolanaAddress(addressInput.trim())
                  ? "linear-gradient(135deg, var(--accent), #0d9488)"
                  : "var(--surface)",
                color: isValidSolanaAddress(addressInput.trim()) ? "#060b0f" : "var(--text-muted)",
                fontSize: "15px",
                fontWeight: "600",
                border: "none",
                cursor:
                  connectLoading || !isValidSolanaAddress(addressInput.trim())
                    ? "not-allowed"
                    : "pointer",
                opacity: connectLoading ? 0.7 : 1,
              }}
            >
              {connectLoading ? "Saving…" : "Save Address"}
            </button>
          </>
        )}

        {error && (
          <div
            style={{
              marginTop: "16px",
              padding: "12px 14px",
              borderRadius: "8px",
              backgroundColor: "var(--error-dim)",
              border: "1px solid var(--error)",
              color: "var(--error)",
              fontSize: "13px",
            }}
          >
            {error}
          </div>
        )}

        {onDismiss && !showConfirmReplace && (
          <button
            onClick={onDismiss}
            style={{
              marginTop: "16px",
              width: "100%",
              padding: "10px",
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Skip for now — set up wallet later
          </button>
        )}
      </div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(modal, document.body);
}
