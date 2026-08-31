# face-chain-verify

A pipeline that takes a face scan image, finds a real matching social media
post via a genuine live reverse-image search, and notarizes that post's
cryptographic fingerprint on an EVM-compatible blockchain — then proves the
on-chain record is tamper-evident by re-verifying it and showing that any
modification breaks verification.

Built for HH Goa 2026 Shortlisting Task 3.

## Consent & scope note

This pipeline is built and demonstrated using the **operator's own face** (or
a willing, consenting subject's). Face-driven identity discovery of
unconsenting third parties is out of scope for this project by design — the
code is general-purpose, but it's intended to be run against a subject who
has agreed to be identified. Please use it the same way.

## Architecture

```
 ┌─────────────┐     ┌────────────────┐     ┌───────────────┐     ┌──────────────────┐
 │  Face scan   │     │  face_engine   │     │ search_engine │     │ blockchain_engine │
 │  (JPEG/PNG)  │ ──> │ detect + crop  │ ──> │ live reverse  │ ──> │  hash payload,    │
 │              │     │ + HOG encoding │     │ image search  │     │  deploy + store   │
 └─────────────┘     └────────────────┘     │ (SerpApi /    │     │  on EvidenceReg-  │
                                             │  Google Lens) │     │  istry.sol        │
                                             └───────────────┘     └─────────┬─────────┘
                                                                              │
                                                                              v
                                                                   ┌──────────────────┐
                                                                   │  verify_engine     │
                                                                   │  re-verify hash    │
                                                                   │  vs on-chain data, │
                                                                   │  prove tamper      │
                                                                   │  detection         │
                                                                   └──────────────────┘
```

**Pipeline shape:** face scan → face detection/encoding → live web search for
a matching post → hash the discovered post (metadata + image bytes) →
notarize the hash on-chain → recompute + re-verify against the chain →
tamper the data and prove verification now fails.

## Project structure

```
face-chain-verify/
├── contracts/
│   └── EvidenceRegistry.sol      # on-chain evidence store
├── scripts/
│   └── compile.js                # compiles the contract via npm's solc
├── src/
│   ├── face_engine.py            # Step 1: face detection + encoding
│   ├── search_engine.py          # Step 2: live reverse-image search
│   ├── blockchain_engine.py      # Steps 3+4: hashing, deploy, store, verify
│   └── verify_engine.py          # Step 5: re-verification + tamper detection
├── tests/
│   ├── test_full_flow.py                 # integration test, steps 1/3/4/5
│   └── test_search_engine_contract.py    # proves search never fabricates data
├── sample_data/                  # sample image + generated evidence (gitignored)
├── build/                        # compiled contract artifact (generated)
├── main.py                       # CLI entry point, orchestrates all steps
├── requirements.txt
├── package.json                  # only used to install the solc compiler
├── .env.example
└── README.md
```

## How it works, step by step

### Step 1 — Face detection & encoding (`src/face_engine.py`)
Uses OpenCV's bundled Haar Cascade classifier to detect the largest face in
the input image (no model download needed, works offline) and crops it. The
crop is converted to a HOG (Histogram of Oriented Gradients) feature vector
as its "encoding" — a real, classical CV descriptor, not a stub.

> **Swap-in point:** `FaceEngine._build_encoding()` is the only method that
> needs to change to use `face_recognition` (dlib, 128-d embeddings) or
> `deepface` (FaceNet/ArcFace, deep embeddings) for production-grade
> accuracy. Everything downstream only depends on getting back a cropped
> face image + a numeric vector, so no other file needs to change.

### Step 2 — Dynamic web/social media search (`src/search_engine.py`)
Performs a **genuine, live** reverse-image search using
[SerpApi's Google Lens engine](https://serpapi.com/google-lens-api). Since
Google Lens needs a URL it can fetch, the face crop is first uploaded to
[0x0.st](https://0x0.st) (an anonymous, ephemeral file host — no account
needed), then that URL is handed to SerpApi. The first social-media domain
match (Twitter/X, Instagram, LinkedIn, Reddit, Facebook, TikTok, Pinterest)
is picked, falling back to the top visual match if none is social.

**This step never fabricates a result.** If `SERPAPI_API_KEY` isn't set, it
raises `SearchBackendUnavailable` instead of returning fake data — see
`tests/test_search_engine_contract.py`.

### Step 3 — Hashing & payload packaging (`src/blockchain_engine.py`)
The matched post's metadata (`post_url`, `author`, `post_text`, `image_url`,
`timestamp`) is serialized to canonical JSON (sorted keys, no whitespace
ambiguity), concatenated with the raw downloaded image bytes, and hashed with
**keccak256** — the same hash function Solidity's `bytes32`/`keccak256()`
use natively, so the Python-computed digest is exactly what the contract
expects, with no format translation.

### Step 4 — Smart contract & blockchain layer (`contracts/EvidenceRegistry.sol`)
```solidity
function storeRecord(bytes32 _postHash, string calldata _postUrl) external;
function verifyRecord(bytes32 _postHash) external view
    returns (bool isValid, uint256 timestamp, address submitter);
```
`storeRecord` writes a `{timestamp, submitter, postUrl}` record keyed by the
hash. `verifyRecord` is a free, read-only call: pass in a hash, get back
whether a record with that *exact* hash exists. The chain never stores the
post text or image — only its fingerprint — so no personal data lives
on-chain.

The contract is compiled via `scripts/compile.js`, which uses the **npm
`solc` package** (a WASM build of the real Solidity compiler) rather than
`py-solc-x`, because `py-solc-x` fetches compiler binaries from
`binaries.soliditylang.org`, which is blocked on some locked-down networks
(including the sandbox this was built in). The npm registry route works
everywhere `npm install` works.

### Step 5 — Re-verification & tamper detection (`src/verify_engine.py`)
1. Reloads the locally saved evidence, recomputes its hash, calls
   `verifyRecord()` — asserts `isValid == True`.
2. Flips one character in the post text, recomputes the hash, calls
   `verifyRecord()` again — asserts `isValid == False`.
3. Flips one byte in the image bytes, recomputes the hash, calls
   `verifyRecord()` again — asserts `isValid == False`.

This is the actual proof of tamper-resistance: a single bit changed anywhere
in the evidentiary payload produces a completely different hash, which no
longer matches any record on-chain.

## Setup

### 1. Install dependencies
```bash
git clone <this-repo>
cd face-chain-verify
pip install -r requirements.txt
npm install          # installs the solc compiler used by scripts/compile.js
```

### 2. Configure environment
```bash
cp .env.example .env
```
Edit `.env`:
- `SERPAPI_API_KEY` — required for Step 2. Get a free key at
  [serpapi.com](https://serpapi.com/) (100 free searches/month).
- `CHAIN_MODE` — `local` (default, no setup) or `rpc` (see below).

### 3. Compile the contract
```bash
node scripts/compile.js
```
This writes `build/EvidenceRegistry.json` (ABI + bytecode), which
`blockchain_engine.py` loads at runtime.

### 4. Run the full pipeline
```bash
python main.py --image path/to/your_face_scan.jpg
```
This runs all five steps in order and prints a final tamper-detection report.

### 5. Run the tests
```bash
python tests/test_full_flow.py
python tests/test_search_engine_contract.py
```

## Blockchain setup options

`CHAIN_MODE` in `.env` selects the backend:

**`local` (default)** — an in-process simulated EVM chain via `eth-tester` +
`py-evm`. No external node, no Anvil/Hardhat binary, no faucet, no RPC URL.
Fully offline, deterministic, and what this repo's own tests use. Every
`python main.py` run deploys a fresh contract instance on a throwaway chain.

**`rpc`** — connect to any real JSON-RPC endpoint:
- **Local Anvil node** (if you have [Foundry](https://getfoundry.sh)
  installed): run `anvil` in a separate terminal, then set
  `RPC_URL=http://127.0.0.1:8545` and `PRIVATE_KEY=<one of anvil's printed
  test keys>`.
- **Local Hardhat node**: `npx hardhat node`, then same as above with
  Hardhat's printed test account key.
- **Public testnet** (Sepolia, Polygon Amoy, etc.): set `RPC_URL` to an
  Infura/Alchemy/public RPC endpoint and `PRIVATE_KEY` to a funded testnet
  wallet's private key (get test funds from that network's faucet). The
  same `storeRecord`/`verifyRecord` calls work unchanged — `web3.py` doesn't
  care whether the chain is simulated or real.

To reuse an already-deployed contract instead of redeploying on every run,
set `CONTRACT_ADDRESS` in `.env` after your first deployment.

## Known limitations & assumptions

- **Face encoding is a classical CV descriptor (HOG), not a deep embedding.**
  This was a deliberate simplicity trade-off (see YAGNI note in
  `face_engine.py`) — it's a real, working descriptor, but `face_recognition`
  (dlib) or `deepface` would give materially better accuracy for
  distinguishing similar-looking faces. The code is structured so swapping
  this in is a one-method change.
- **Reverse image search quality depends entirely on SerpApi/Google Lens's
  index.** For faces with no public web presence, Step 2 will legitimately
  find nothing (`NoMatchFoundError`) — this is expected behavior, not a bug,
  since the task requires a genuine search rather than a guaranteed hit.
- **The image-hosting step (0x0.st) is a public, ephemeral, anonymous
  upload** used only to give the search API a fetchable URL. It is not meant
  for sensitive data retention; swap for a private signed-URL bucket
  (S3/Cloudinary) if that matters for your use case.
- **`storeRecord` reverts on an exact-duplicate hash** (`already exists`) by
  design, to keep the mapping a genuine append-only evidence log. Running
  the pipeline twice on identical post data against the same deployed
  contract will fail on the second `storeRecord` call — deploy a fresh
  contract (default `local` mode does this automatically) or use a new
  post/subject.
- **`CHAIN_MODE=local` is not persistent** — the simulated chain lives only
  for the process's lifetime. This is intentional for a reproducible demo;
  switch to `rpc` mode for a persistent, publicly-checkable record.
- **This was developed and tested in a network-restricted sandbox** that
  could reach PyPI/npm/GitHub but not `serpapi.com`, `0x0.st`, or
  `binaries.soliditylang.org`. Steps 1, 3, 4, and 5 were verified fully
  end-to-end there (see `tests/test_full_flow.py`); Step 2's live search
  call itself needs to be exercised in an environment with normal internet
  access and a real `SERPAPI_API_KEY`.

## Tech stack

- **Face detection/encoding**: OpenCV (Haar Cascade + HOG)
- **Search**: SerpApi (Google Lens engine)
- **Hashing**: keccak256 via `web3.py`
- **Smart contract**: Solidity ^0.8.24, compiled via npm `solc`
- **Chain interaction**: `web3.py` + `eth-tester`/`py-evm` (local) or any
  JSON-RPC endpoint (testnet/mainnet)
