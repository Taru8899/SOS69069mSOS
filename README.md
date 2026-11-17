# SOS69069 mSOS
https://drive.google.com/drive/folders/1H21g8Ai3RDc4Nd6vCg0Xt0fp5uNu3kXj

https://github.com/Taru8899/SOS69069mSOS/actions/runs/44166643785

0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A

**SOS69069 mSOS**

**Permanent · public · owned by no One.**

Everything is public. Nothing is private.  
Decentralised.

---

### Part 1 — User Instructions (plain language)

SOS69069 mSOS is an on-chain messaging app. There is **no chat server**, **no account signup**, and **no central delete button**. Messages are signed records written permanently on Ethereum. Anyone can read them. They are ordered by time.

You post short public messages (up to 64 characters of metadata) through the **SOS 69069** contract. Gas is paid by a relayer key that you control (or by the demo key while you try the app).

#### What you can do

| You can… | How |
|----------|-----|
| Read a public message board | **BOARD** tab → the main ledger (and any extra boards you add) |
| Hold a chat around one address | **CHAT** tab → set a target address, refresh, reply with short codes |
| Keep self-notes / a private stream to yourself | **MIND** tab → messages you post to yourself; optional temporary bind of one other address for this session only |
| Pay gas without a backend | **SETUP** → paste or generate a relayer private key that signs the on-chain submit |

Nothing important is stored on a server you do not control. Keys and settings stay on **this device**, and only if you turn on **Save my data on device** (or **Remember on device**) in SETUP.

#### The four tabs (order in the app)

**BOARD · CHAT · MIND · SETUP**

- **BOARD** — Public boards. The main SOS ledger is always available. Add more board addresses in SETUP. Boards are listed by activity; tap one to select and load messages. Short-code replies are supported.
- **CHAT** — Messages aimed at one target address (anyone can post to that target). Refresh saves the address and scans. Replies can include a short code so threads stay followable. The target can be kept after restart when device save is enabled.
- **MIND** — Self-records only (you sign messages intended for yourself). Optional bind of another address for this session only (cleared when the app closes). Refresh applies the key, applies the bind, and scans in one step.
- **SETUP** — Wallet (paste or generate a private key), RPC, Etherscan API key, max gas fee, relayer key, extra board addresses, discovery codes, and the **Save my data on device** switch.

#### Save my data on device

- Off by default (safe demo defaults so you can try the app).
- While off, demo keys may be shown; anything you type is session-only.
- Turn the switch **on**, then tap **Save settings**, to keep your own key, chat target, and relayer key on this device.
- Turn it **off** and **Save settings** again to stop persisting those overrides.

Board message caches are only local read caches of chain data (capped per board). They are not a substitute for the ledger itself.

#### How a message works (simple)

1. You write text (≤ 64 characters in the on-chain metadata field).
2. Your wallet signs an EIP-712 record for the SOS 69069 contract.
3. A relayer key submits the transaction and pays the gas.
4. Anyone can read that record from the chain (via Etherscan API / RPC inside the app).

| Mode | Who the record is aimed at (`intendedTo`) |
|------|-------------------------------------------|
| **MIND** | Yourself |
| **CHAT** | The chat target address |
| **BOARD** | The selected board address (ledger or extra) |

When a message is on-chain the app shows a short `tx…` link. Tap it to open the transaction on Etherscan.

#### Safety

- Treat any private key you paste like cash: it can sign messages and spend gas.
- **Save my data on device** writes secrets into the app’s private storage. That is not shared with other apps, but it is not safe against physical access to an unlocked or compromised device.
- Demo keys are for exploration only — do not fund them with money you cannot lose.

**Tagline:** SOS69069 mSOS – owned by no One.

---

### Part 2 — Technical Explanation

#### Contract

| | |
|--|--|
| **SOS ledger (contract)** | `0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A` |
| **Network** | Ethereum mainnet |
| **Explorer** | [Etherscan](https://etherscan.io/address/0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A) |

This address is the built-in **BOARD** ledger. Extra boards are optional addresses you add in SETUP.

Source / related: https://github.com/Taru8899/69069 (and related repos under the same account).

#### Core design

- Pure on-chain event ledger. No assets are held, nothing is executed on behalf of users, no admin/owner/upgrade path.
- Every successful call writes one atomic record containing:
  - signer
  - intended address (`intendedTo`)
  - payload hash
  - raw signature
  - free-form metadata (capped at 64 characters)
- Writing a record increments two independent counters: `pushOf[signer]` and `trustOf[intendedTo]`. A global `phaseTotal` also increments.
- Effective value for an address = `trustOf − pushOf` (exposed as signed integer; wallets see a non-negative view via `balanceOf`).
- The contract deliberately exposes an ERC-20-compatible surface (`name` = "69069", `symbol` = "SOS", `decimals` = 0, Transfer events with value 1) purely for display / explorer friendliness. Nothing is transferable.

#### Message flow (technical)

1. Client constructs an EIP-712 typed data structure for the SOS 69069 contract (signer, intendedTo, payload hash, metadata).
2. User’s private key signs the structured data off-chain.
3. A separate **relayer** private key (controlled by the user or a demo key) submits the signed record on-chain and pays gas.
4. The contract verifies the signature (ecrecover / exact match), writes the permanent record, emits events, and updates counters.
5. Clients read records via RPC + Etherscan API (or equivalent). Local caches are read-only, size-capped per board, and never authoritative.

Modes map directly to the `intendedTo` field:

- **MIND** → `intendedTo` = signer’s own address
- **CHAT** → `intendedTo` = user-chosen target address
- **BOARD** → `intendedTo` = selected board/ledger address

#### Client storage & keys

- Keys, RPC endpoint, Etherscan API key, max gas, extra boards, discovery codes, and chat target live only on-device.
- Persistence is gated by the explicit “Save my data on device” flag + “Save settings” action. Default is session-only / demo-safe.
- Relayer key is independent of the signing key so the user can separate signing authority from gas payment.

#### Safety properties of the contract (as designed)

- Rejects direct ETH transfers.
- Non-zero address checks.
- No selfdestruct, no proxy, no privileged roles.
- Metadata length and batch sizes are capped.
- Duplicate signed structs are rejected.

The app is a thin client over this immutable ledger. All durable state lives on Ethereum; the client only signs, submits, and reads.
