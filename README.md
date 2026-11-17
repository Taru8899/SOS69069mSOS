# SOS69069 mSOS
https://drive.google.com/drive/folders/1H21g8Ai3RDc4Nd6vCg0Xt0fp5uNu3kXj

https://github.com/Taru8899/SOS69069mSOS/actions/runs/44166643785

0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A

**SOS69069 mSOS**

**Permanent · public · owned by no One.**

Decentralised. Trustless. Yours.  
Everything is public. Nothing is private.

---

### Part 1 — User Instructions (plain language)

SOS69069 mSOS is an on-chain messaging app for Android. There is **no chat server**, **no account signup**, and **no central delete button**. Messages are signed records written permanently on Ethereum. Anyone can read them. They are ordered by block time.

**The app never holds a private key.** You connect your own wallet (WalletConnect). The wallet signs every message and sends the transaction, so you pay the gas yourself and you approve every step on your own device.

#### What you can do

| You can… | How |
|----------|-----|
| Read and post on a public message board | **Board** tab → the main SOS ledger, plus any extra board addresses you add in Settings |
| Keep notes for yourself, or follow what other addresses write to themselves | **Mind** tab → your own notes, plus addresses you choose to watch |
| Talk with one or more addresses | **Chat** tab → a conversation between you and 1–3 other addresses |
| Write a new message anywhere | The blue **+** button, shown on every page |

#### The three pages and Settings

All three pages share the same look and the same tools:

- **Message cards.** Each message is a white card: a round avatar (first two characters of the sender's address), the message text, a small grey line (sender, effective value, block, age, number of replies) and a light-blue **reply code** box on the right. Tap the card for details, tap the code box to reply.
- **Block time.** Time always means the time of the Ethereum block that holds the record. Messages are grouped under block headings, newest first.
- **10 at a time.** Each page shows 10 messages and a **Load more** button. The Board always tries to show at least 4 messages the first time it opens.
- **Pull down to reload.** Every page (and Settings) reloads when you pull it down.
- **Fold header.** Just above the messages sits a header with the page name and a triangle (Board: the board name, e.g. **Ledger**; Mind: **Me 0x…**; Chat: **Chat with**). Tap it to hide or show the address chips, tags and filters. While it is closed it shows what is selected. The page remembers whether it was open or closed.
- **Tags.** A row **All tags · your saved tags · + Save tag** lets you group messages by a tag. Save tags in Settings.
- **Reply-code threads.** Every message has a 3-character reply code (for example `kg6`). Replies start with `@kg6`. Save `kg6` as a tag (or tap **Replies to kg6** in the message details) and the page lists that message together with all its replies.

**Board** — messages addressed to a board. Sorts: Newest block, Sender eff high, Eff 10 or more, Most replies. Add more boards in Settings.

**Mind** — messages you sign to yourself, plus the self-messages of addresses you watch (add them in Settings). Scope: All, Mine, Watched. Sorts: Newest block, Eff high.

**Chat** — pick or paste an address and tap **New chat**; tap **Add to this chat** to make a conversation of 2 or more addresses (you plus up to 3 others). Messages are coloured by sender: you in dark green, the others in blue, purple and orange (a legend of coloured chips shows who is who). Filters: All, Sent A to B, Received B to A, Replies.

**Settings** — the ledger address (copy / open on Etherscan), your Etherscan key, boards, watched addresses, saved tags, and **Clear saved messages**. Use the **Paste** button next to a field to take the text from your clipboard and add it at once. There is no separate Save or Add button.

#### Sending a message

1. Tap the blue **+** (or **Reply** on a card), choose where it goes (Board, Mind or a Chat conversation) and write. Long text is split into lines of at most 64 bytes; one message can have several lines.
2. Tap **Sign**. Your wallet asks you to sign each line (EIP-712 typed data), then to send one transaction.
3. The app checks the transaction before the wallet sends it, then follows it until it is in a block.
4. On success you see the **transaction link** (open it on Etherscan or copy the hash). On failure you see a plain explanation of what went wrong (cancelled in the wallet, wrong account, not enough gas, rejected by the contract, timeout, network) and the raw error to copy.
5. After a message is sent from **Mind**, that page does not reload for about a minute, so your waiting message stays visible until the block arrives. A message that is sent but not yet in a block is shown as "waiting".

#### What is kept on the phone

- **Board and Chat messages are saved locally** and shown at once the next time you open the app, even offline. Only new blocks are fetched.
- **Closing the app or exiting the wallet:** all Chat data stays. Mind keeps only your own self-messages; everything that belongs to watched addresses is removed and the watch list is cleared. Your Etherscan key is always kept. The default Board messages, your added boards and your saved tags stay.
- **Clear saved messages** in Settings removes the local message files (they are fetched again from the chain).

Saved messages are only a read cache of chain data. They are never a substitute for the ledger itself.

#### Etherscan key

The app reads the chain through Etherscan (with your key) and falls back to a public RPC. The public RPC is slow and sometimes refuses large searches, so **an Etherscan API key is recommended**. Paste it in Settings.

#### Safety

- Your private key stays in your wallet. mSOS cannot sign or spend anything without your approval in the wallet.
- Always read what your wallet asks you to sign and send.
- Everything you post is public and permanent. Nothing can be edited or deleted.

**Tagline:** SOS69069 mSOS – owned by no One.

---

### Part 2 — Technical Explanation

#### Contract

| | |
|--|--|
| **SOS ledger (contract)** | `0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A` |
| **Network** | Ethereum mainnet |
| **Explorer** | [Etherscan](https://etherscan.io/address/0x7373DBC24Dcd785896E8Ac3d5372c6ced9B75a8A) |

This address is the built-in **Board** ledger. Extra boards are optional addresses you add in Settings.

Source / related: https://github.com/Taru8899/69069 (and related repos under the same account).

#### Core design

- Pure on-chain event ledger. No assets are held, nothing is executed on behalf of users, no admin/owner/upgrade path.
- Every successful call writes one atomic record, emitted as the event `SignatureRecorded(signer, intendedTo, payloadHash, signature, submitter, timestamp, metadata)`:
  - signer
  - intended address (`intendedTo`)
  - payload hash
  - raw signature
  - submitter (the address that sent the transaction)
  - timestamp
  - free-form metadata (capped at 64 bytes)
- Writing a record increments two independent counters: `pushOf[signer]` and `trustOf[intendedTo]`. A global `phaseTotal` also increments.
- Effective value ("eff") for an address = `trustOf − pushOf`. The cards show the sender's eff.
- The contract exposes an ERC-20-compatible surface (`name` = "69069", `symbol` = "SOS", `decimals` = 0, Transfer events with value 1) purely for display / explorer friendliness. Nothing is transferable.

#### Message flow (technical)

1. The app splits your text into lines of at most 64 bytes. Each line becomes one record.
2. For every line the app asks the wallet for `eth_signTypedData_v4` (EIP-712 typed data for the SOS 69069 contract: signer, intendedTo, payload hash, metadata).
3. The app dry-runs the call (simulation) so that errors are explained before the wallet is asked to send.
4. The wallet sends **one** transaction with `eth_sendTransaction`; several lines go in one batch call. The signer is also the submitter and pays the gas. There is no relayer.
5. The app polls the receipt until the transaction is in a block, then shows the link or the error.
6. The contract verifies the signatures, writes the permanent records, emits the events and updates the counters.

All records of one transaction, one signer and one recipient form **one message** (its lines in order).

Modes map directly to the `intendedTo` field:

- **Mind** → `intendedTo` = signer's own address
- **Chat** → `intendedTo` = the other address of the conversation
- **Board** → `intendedTo` = the selected board address (the ledger or an extra board)

#### Reading the chain

| View | Event query (`signer`, `intendedTo`) |
|------|--------------------------------------|
| Board | any signer → the board address |
| Mind | your address → your address, and the same for each watched address |
| Chat | every ordered pair among you and the conversation's addresses (A→B, B→A, B→C …) |

- Logs come from the Etherscan `getLogs` API (with your key) or, as a fallback, from a public RPC in windows of about two days of blocks per step.
- Time shown is the block time of the record.
- **Reply code** = 3 base-36 characters derived from the payload hash of the message's first record. A reply writes `@code` at the start of its first line. Tags are `#word` in the text. A saved tag of the form `@code` selects the message with that code and all its replies.

#### Wallet connection

- WalletConnect, through the same wallet bridge as dSOS (JavaScript glue in `wc/`). The app name shown in the wallet is **mSOS**.
- The session requests Ethereum mainnet only (eip155:1); other chains are optional and filtered out, so wallets that do not support Sepolia connect without an error.

#### Client storage

- Settings (address, Etherscan key, boards, watched addresses, saved tags, chats, selected filters, fold state) live in the app's private storage on the device.
- Messages are cached per view (one file for each board, each Mind address set and each Chat conversation) as JSON together with the block range that was searched. Writes are atomic. The cache keeps at most 2,000 records per view, and the newest 64 blocks are always searched again so a chain reorganisation cannot leave stale data.
- Exit rules: Chat cache and Etherscan key are always kept; Mind keeps only your own self-messages and drops the watch list and everything from watched addresses.
- No private key is stored anywhere in the app.

#### Safety properties of the contract (as designed)

- Rejects direct ETH transfers.
- Non-zero address checks.
- No selfdestruct, no proxy, no privileged roles.
- Metadata length and batch sizes are capped.
- Duplicate signed structs are rejected.

The app is a thin client over this immutable ledger. All durable state lives on Ethereum; the client only asks your wallet to sign and send, and reads.
