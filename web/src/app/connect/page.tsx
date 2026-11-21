"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { SiteNav } from "@/components/site-nav";
import { providerRequest, type Provider, type ProviderConnectionStatus } from "@/lib/provider-connection";

export default function ConnectPage() {
  const [status, setStatus] = useState<ProviderConnectionStatus | null>(null);
  const [provider, setProvider] = useState<Provider>("codex");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loginUrl, setLoginUrl] = useState("");

  const refresh = useCallback(async () => {
    const next = await providerRequest<ProviderConnectionStatus>();
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    let active = true;
    providerRequest<ProviderConnectionStatus>().then(next => {
      if (!active) return;
      setStatus(next);
      if (next.connection) { setProvider(next.connection.provider); setModel(next.connection.model); }
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : "Couldn't load AI setup. Reload the page."); });
    return () => { active = false; };
  }, []);

  async function action(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await work(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Couldn't connect. Try again."); }
    finally { setBusy(false); setKey(""); }
  }

  function connect(method: "existing_cli" | "subscription" | "api_key") {
    void action(async () => {
      const result = await providerRequest<{ url?: string }>("", "POST", { provider, model: model.trim(), method, ...(method === "api_key" ? { api_key: key } : {}) });
      if (result.url) setLoginUrl(result.url);
      else setMessage(method === "api_key" ? "Key saved. Now check that it works." : "Connected. Now check that it works.");
      await refresh();
    });
  }

  const button = "rounded-md brutal-border px-5 py-3 text-sm font-bold cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";
  const pending = Boolean(status?.pending_login);
  return <div className="min-h-screen bg-surface text-txt-primary">
    <SiteNav showAccount={false} />
    <main className="mx-auto w-full max-w-xl px-5 py-10 sm:py-16">
      <h1 className="font-[family-name:var(--font-heading)] text-3xl font-bold">Connect your AI</h1>
      <p className="mt-3 text-txt-secondary">Use your own AI account to make games here. You pay for the usage.</p>
      {error && <p role="alert" className="mt-5 rounded-md border border-pop-red/40 p-4 text-sm text-pop-red">{error}</p>}
      {message && <p role="status" className="mt-5 text-sm text-pop-lime">{message}</p>}
      {!status && !error && <p role="status" className="mt-6">Loading…</p>}

      {status && <>
        {status.connection && <section aria-label="Current AI connection" className="mt-6 rounded-xl border border-white/10 bg-surface-raised p-5">
          <p className="font-bold">{status.connection.provider === "codex" ? "Codex" : "Claude Code"} is connected</p>
          <p className="mt-1 text-sm text-txt-muted">{status.connection.model || "Default model"} · {status.connection.kind === "existing_cli" ? "Uses your login on this computer" : "Saved on this computer"}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link className={`${button} bg-pop-yellow text-surface`} href="/create">Make a game</Link>
            <button className={`${button} text-txt-secondary`} disabled={busy || pending} onClick={() => void action(async () => {
              await providerRequest("/check", "POST"); setMessage("Connected");
            })}>{busy ? "Working…" : "Check connection"}</button>
          </div>
          <p className="mt-3 text-xs text-txt-muted">Checking uses a tiny bit of your AI account.</p>
          <button className="mt-4 text-sm text-txt-muted underline cursor-pointer disabled:opacity-40" disabled={busy} onClick={() => void action(async () => {
            await providerRequest("", "DELETE"); setLoginUrl(""); await refresh(); setMessage("Disconnected. Your login on this computer is unchanged.");
          })}>Disconnect</button>
        </section>}

        <section aria-label="Choose AI provider" className="mt-8 space-y-5">
          <div className="flex gap-3">
            {(["codex", "claude"] as const).map(value => <button key={value} disabled={busy || pending} aria-pressed={provider === value}
              className={`${button} flex-1 ${provider === value ? "bg-pop-yellow text-surface" : "bg-surface-raised text-txt-secondary"}`}
              onClick={() => { setProvider(value); setModel(""); setKey(""); setError(""); setMessage(""); }}>
              {value === "codex" ? "Codex" : "Claude Code"}
            </button>)}
          </div>
          {!status.installed[provider] && <p role="status" className="text-sm text-txt-secondary">
            Install {provider === "codex" ? "Codex" : "Claude Code"} on this computer, then reload this page.
            {" "}<a className="underline" href={provider === "codex" ? "https://learn.chatgpt.com/docs/cli" : "https://code.claude.com/docs/en/setup"} target="_blank" rel="noreferrer">How to install</a>
          </p>}

          {pending ? <div className="rounded-xl border border-white/10 p-5">
            <h2 className="font-bold">Finish signing in with ChatGPT</h2>
            <p className="mt-2 text-sm text-txt-secondary">Sign in in the other tab, then come back. You have 10 minutes.</p>
            {loginUrl && <a href={loginUrl} target="_blank" rel="noreferrer" className={`${button} mt-4 inline-block bg-pop-yellow text-surface`}>Open ChatGPT sign-in</a>}
            {!loginUrl && <p className="mt-3 text-sm text-txt-secondary">Use the tab you already opened, or cancel and start again.</p>}
            <div className="mt-4 flex flex-wrap gap-3">
              <button className={button} disabled={busy} onClick={() => void action(async () => {
                const result = await providerRequest<{complete: boolean}>("/login/finish", "POST");
                if (result.complete) { setLoginUrl(""); await refresh(); setMessage("ChatGPT connected. You're ready to make a game."); }
                else setMessage("Not signed in yet. Finish in the other tab, then try again.");
              })}>I’ve signed in</button>
              <button className={button} disabled={busy} onClick={() => void action(async () => {
                await providerRequest("/login/cancel", "POST"); setLoginUrl(""); await refresh();
              })}>Cancel sign-in</button>
            </div>
          </div> : <>
            {provider === "codex" ? <button className={`${button} w-full bg-pop-yellow text-surface`} disabled={busy || !status.installed.codex} onClick={() => connect("subscription")}>Sign in with ChatGPT</button> :
              <p className="text-sm text-txt-secondary">To use a Claude subscription, run <code className="text-txt-primary">claude auth login</code> in your terminal. Then press the button below.</p>}
            <button className={`${button} w-full bg-surface-raised`} disabled={busy || !status.installed[provider]} onClick={() => connect("existing_cli")}>Use existing {provider === "codex" ? "Codex" : "Claude Code"} login</button>
            <details className="rounded-lg border border-white/10 p-4">
              <summary className="cursor-pointer text-sm">Use an API key instead</summary>
              <form className="mt-4 space-y-3" onSubmit={event => { event.preventDefault(); connect("api_key"); }}>
                <label className="block text-sm">{provider === "codex" ? "OpenAI" : "Anthropic"} API key
                  <input type="password" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} maxLength={4096} disabled={busy}
                    className="mt-2 w-full rounded-md brutal-border bg-surface px-3 py-3 outline-none focus:ring-2 focus:ring-pop-yellow" />
                </label>
                <p className="text-xs text-txt-muted">API keys are billed separately from subscriptions. The key stays on this computer.</p>
                <button className={`${button} bg-pop-yellow text-surface`} disabled={busy || !key.trim() || !status.installed[provider]} type="submit">Save API key</button>
              </form>
            </details>
            <details className="text-sm text-txt-secondary">
              <summary className="cursor-pointer">Model (optional)</summary>
              <label className="mt-3 block">Model identifier
                <input value={model} maxLength={120} onChange={event => setModel(event.target.value)} disabled={busy}
                  placeholder="Default" className="mt-2 w-full rounded-md brutal-border bg-surface-raised px-3 py-3 text-txt-primary" />
              </label>
              <p className="mt-2 text-xs">Set this before you connect.</p>
            </details>
          </>}
        </section>
        <p className="mt-10 border-t border-white/10 pt-5 text-xs leading-relaxed text-txt-muted">Your TinyWorlds account saves games. It does not pay for AI. Paid pictures and sounds need their own keys.</p>
      </>}
    </main>
  </div>;
}
