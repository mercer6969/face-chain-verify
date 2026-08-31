"""
blockchain_engine.py
---------------------
Steps 3 + 4 of the pipeline: hashing/packaging the discovered post, and
storing/verifying it on an EVM-compatible chain.

Chain backends (choose via .env, see README):
  - "local"  (default): an in-process simulated EVM via eth-tester + py-evm.
             No external node, no Anvil/Hardhat binary, no faucet needed --
             works fully offline and is what CI / this sandbox uses.
  - "rpc"    : connect to any real JSON-RPC endpoint (a local Anvil/Hardhat
             node, or a public testnet like Sepolia / Polygon Amoy) using
             RPC_URL + PRIVATE_KEY from .env.

Contract: contracts/EvidenceRegistry.sol (compiled via scripts/compile.js
into build/EvidenceRegistry.json before this module is used).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3
from web3.middleware import SignAndSendRawMiddlewareBuilder
from web3.providers.eth_tester import EthereumTesterProvider

ROOT_DIR = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT_DIR / "build" / "EvidenceRegistry.json"


# --------------------------------------------------------------------------- #
# Hashing / payload packaging (Step 3)
# --------------------------------------------------------------------------- #

def build_canonical_payload(post_meta: dict, image_bytes: bytes) -> bytes:
    """Deterministically serialize post metadata + image bytes into one payload.

    Determinism matters: the same logical data must always hash to the same
    value, and any single-character/byte change anywhere must change the hash.
    We do this by:
      1. Sorting metadata keys and using compact, fixed separators (no
         whitespace ambiguity) when dumping to JSON.
      2. Concatenating the UTF-8 metadata JSON with the raw image bytes,
         separated by a fixed delimiter that cannot appear inside the JSON.
    """
    canonical_json = json.dumps(post_meta, sort_keys=True, separators=(",", ":"))
    return canonical_json.encode("utf-8") + b"||IMG||" + image_bytes


def compute_hash(post_meta: dict, image_bytes: bytes) -> bytes:
    """Compute the keccak256 digest (bytes32) of the canonical payload.

    keccak256 (not SHA-256) is used because it is the native hash Solidity's
    `bytes32` / `keccak256()` uses, so the same digest computed here in Python
    is exactly what storeRecord()/verifyRecord() expect on-chain -- no
    hash-format translation needed.
    """
    payload = build_canonical_payload(post_meta, image_bytes)
    return Web3.keccak(payload)


# --------------------------------------------------------------------------- #
# Chain connection (Step 4)
# --------------------------------------------------------------------------- #

@dataclass
class ChainConfig:
    mode: str          # "local" or "rpc"
    rpc_url: str | None = None
    private_key: str | None = None


def load_chain_config_from_env() -> ChainConfig:
    mode = os.getenv("CHAIN_MODE", "local").lower()
    return ChainConfig(
        mode=mode,
        rpc_url=os.getenv("RPC_URL"),
        private_key=os.getenv("PRIVATE_KEY"),
    )


class EvidenceRegistryClient:
    """Thin wrapper around web3.py for deploying/using EvidenceRegistry.sol."""

    def __init__(self, config: ChainConfig | None = None):
        self.config = config or load_chain_config_from_env()
        self.w3, self.account = self._connect(self.config)
        self.abi, self.bytecode = self._load_artifact()
        self.contract_address: str | None = os.getenv("CONTRACT_ADDRESS") or None
        self._contract = None
        if self.contract_address:
            self._contract = self.w3.eth.contract(address=self.contract_address, abi=self.abi)

    # -- setup ---------------------------------------------------------- #

    @staticmethod
    def _load_artifact() -> tuple[list, str]:
        if not ARTIFACT_PATH.exists():
            raise FileNotFoundError(
                f"{ARTIFACT_PATH} not found. Run `node scripts/compile.js` first."
            )
        artifact = json.loads(ARTIFACT_PATH.read_text())
        return artifact["abi"], artifact["bytecode"]

    @staticmethod
    def _connect(config: ChainConfig):
        if config.mode == "local":
            tester = EthereumTester(backend=PyEVMBackend())
            w3 = Web3(EthereumTesterProvider(tester))
            account_address = w3.eth.accounts[0]
            return w3, account_address  # eth-tester manages signing itself

        if config.mode == "rpc":
            if not config.rpc_url or not config.private_key:
                raise ValueError(
                    "CHAIN_MODE=rpc requires RPC_URL and PRIVATE_KEY in your .env"
                )
            w3 = Web3(Web3.HTTPProvider(config.rpc_url))
            acct = Account.from_key(config.private_key)
            w3.middleware_onion.inject(
                SignAndSendRawMiddlewareBuilder.build(acct), layer=0
            )
            w3.eth.default_account = acct.address
            if not w3.is_connected():
                raise ConnectionError(f"Could not connect to RPC_URL={config.rpc_url}")
            return w3, acct.address

        raise ValueError(f"Unknown CHAIN_MODE: {config.mode!r} (expected 'local' or 'rpc')")

    # -- deployment ------------------------------------------------------ #

    def deploy(self) -> str:
        """Deploy a fresh EvidenceRegistry contract and return its address."""
        Contract = self.w3.eth.contract(abi=self.abi, bytecode=self.bytecode)
        tx_hash = Contract.constructor().transact({"from": self.account})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        self.contract_address = receipt.contractAddress
        self._contract = self.w3.eth.contract(address=self.contract_address, abi=self.abi)
        return self.contract_address

    @property
    def contract(self):
        if self._contract is None:
            raise RuntimeError("No contract deployed/loaded yet. Call deploy() first "
                                "or set CONTRACT_ADDRESS in .env.")
        return self._contract

    # -- notarization / verification (Step 5 building blocks) ------------ #

    def store_record(self, post_hash: bytes, post_url: str) -> dict:
        """Submit storeRecord(post_hash, post_url) and return the tx receipt info."""
        tx_hash = self.contract.functions.storeRecord(post_hash, post_url).transact(
            {"from": self.account}
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "block_number": receipt.blockNumber,
            "status": receipt.status,
            "contract_address": self.contract_address,
        }

    def verify_record(self, post_hash: bytes) -> dict:
        """Call verifyRecord(post_hash) (read-only, no gas) and return the result."""
        is_valid, timestamp, submitter = self.contract.functions.verifyRecord(post_hash).call()
        return {"is_valid": is_valid, "timestamp": timestamp, "submitter": submitter}


if __name__ == "__main__":
    # Minimal smoke test: deploy, store, verify, then verify a tampered hash.
    from dotenv import load_dotenv

    load_dotenv()

    client = EvidenceRegistryClient()
    addr = client.deploy()
    print(f"Deployed EvidenceRegistry at {addr} (mode={client.config.mode})")

    demo_meta = {"post_url": "https://example.com/p/1", "author": "demo", "post_text": "hello"}
    demo_hash = compute_hash(demo_meta, b"fake-image-bytes")

    receipt = client.store_record(demo_hash, demo_meta["post_url"])
    print("Stored:", receipt)

    result = client.verify_record(demo_hash)
    print("Verify (unmodified):", result)
    assert result["is_valid"] is True

    tampered_hash = compute_hash(demo_meta, b"fake-image-bytesX")  # 1 byte added
    tampered_result = client.verify_record(tampered_hash)
    print("Verify (tampered):", tampered_result)
    assert tampered_result["is_valid"] is False

    print("Smoke test passed.")
