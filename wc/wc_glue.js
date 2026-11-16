// Glue between the Kivy app (Python) and WalletConnect. Python polls drain() about twice a second
// and calls connect / request / disconnect / resume. No key ever exists here: the wallet app signs.
// Messages (objects) put in the queue:
//   {t:"boot"}                                  script is running
//   {t:"uri", uri}                              pairing link: Python opens it in the wallet app
//   {t:"session", accounts, chainId, wallet, native, universal}
//   {t:"result", id, result} / {t:"error", id, error, code}
//   {t:"disconnect"} / {t:"accounts", accounts} / {t:"fatal", error}
export function createGlue(EthereumProvider, win) {
  const cfg = win.__CFG || {};
  const queue = [];
  const out = (o) => { queue.push(o); };
  const msg = (e) => String((e && (e.message || e.reason)) || e);
  let provider = null;
  let initPromise = null;

  async function getProvider() {
    if (provider) return provider;
    if (!initPromise) {
      initPromise = (async () => {
        const p = await EthereumProvider.init({
          projectId: cfg.projectId,
          chains: [1],
          // Ethereum only: the provider adds other networks (Sepolia 11155111 ...) by itself unless
          // this is given, and a wallet such as TokenPocket then complains "network not supported"
          optionalChains: [1],
          // mSOS signs every message line with eth_signTypedData_v4, so it is REQUIRED: a wallet that
          // only approves the required methods would otherwise leave it out of the session, and the
          // provider would then send the request to the public RPC node ("method does not exist").
          methods: ["eth_sendTransaction", "eth_signTypedData_v4"],
          optionalMethods: ["eth_signTypedData", "personal_sign"],
          showQrModal: false,
          metadata: {
            name: cfg.name,
            description: cfg.description,
            url: cfg.url,
            icons: cfg.icons || [],
          },
          rpcMap: { 1: cfg.rpc },
        });
        p.on("display_uri", (uri) => out({ t: "uri", uri }));
        p.on("disconnect", () => out({ t: "disconnect" }));
        p.on("accountsChanged", (a) => out({ t: "accounts", accounts: a }));
        provider = p;
        return p;
      })().catch((e) => { initPromise = null; throw e; });
    }
    return initPromise;
  }

  const NEED = "eth_signTypedData_v4";
  // false only when the session lists its approved methods and this one is missing
  function approves(p, method) {
    try {
      const ns = p.session && p.session.namespaces && p.session.namespaces.eip155;
      if (!ns || !Array.isArray(ns.methods)) return true;
      return ns.methods.includes(method);
    } catch (e) { return true; }
  }

  function sessionInfo(p) {
    const peer = (p.session && p.session.peer && p.session.peer.metadata) || {};
    const red = peer.redirect || {};
    return {
      t: "session",
      accounts: p.accounts || [],
      chainId: Number(p.chainId) || 1,
      wallet: peer.name || "",
      native: red.native || "",
      universal: red.universal || "",
    };
  }

  async function connect() {
    try {
      const p = await getProvider();
      // a session made by an older build (or approved without typed-data signing) is dropped, so
      // the wallet is asked again, this time with the method required
      if (p.session && !approves(p, NEED)) {
        try { await p.disconnect(); } catch (e) { /* ignore */ }
      }
      if (!p.session) {
        // belt and braces: whatever the library put in its proposal, only chain 1 is asked for
        try {
          if (p.rpc && Array.isArray(p.rpc.optionalChains)) {
            p.rpc.optionalChains = p.rpc.optionalChains.filter((c) => Number(c) === 1);
          }
        } catch (e) { /* ignore */ }
        await p.connect();
      }
      out(sessionInfo(p));
    } catch (e) {
      out({ t: "error", id: "connect", error: msg(e), code: e && e.code });
    }
  }

  // params is a JSON string so Python never has to build JS objects
  async function request(id, method, paramsJson) {
    try {
      const p = await getProvider();
      if (!p.session) throw new Error("not connected");
      if (method === NEED && !approves(p, NEED)) {
        const e = new Error("The wallet did not approve " + NEED + ". Press Exit, then connect again " +
          "and accept the signing request. A wallet without typed-data signing cannot be used.");
        e.code = 4200;
        throw e;
      }
      const result = await p.request({ method, params: JSON.parse(paramsJson) });
      out({ t: "result", id, result });
    } catch (e) {
      const text = msg(e);
      // the public node answers "the method ... does not exist/is not available" when the session
      // did not list the method: report it as 4200 so the app can reset the link and ask again
      const code = (method === NEED && /does not exist|not available/i.test(text)) ? 4200 : (e && e.code);
      out({ t: "error", id, error: text, code });
    }
  }

  async function disconnect() {
    try {
      if (provider && provider.session) await provider.disconnect();
    } catch (e) { /* ignore */ }
    out({ t: "disconnect" });
  }

  // called when the app comes back from the wallet: wake the relay connection if it slept
  async function resume() {
    try {
      const r = provider && provider.signer && provider.signer.client &&
        provider.signer.client.core && provider.signer.client.core.relayer;
      if (r && r.connected === false && typeof r.restartTransport === "function") {
        await r.restartTransport();
      }
    } catch (e) { /* ignore */ }
  }

  function drain() { return queue.splice(0, queue.length); }

  function boot() {
    win.addEventListener("error", (ev) => out({ t: "fatal", error: msg(ev && (ev.error || ev.message)) }));
    win.addEventListener("unhandledrejection", (ev) => out({ t: "fatal", error: msg(ev && ev.reason) }));
    out({ t: "boot" });
  }

  return { connect, request, disconnect, resume, drain, boot };
}
