/**
 * compile.js
 * ----------
 * Compiles contracts/EvidenceRegistry.sol using the npm "solc" package
 * (a WASM build of the real Solidity compiler) and writes ABI + bytecode
 * to build/EvidenceRegistry.json.
 *
 * Why compile via Node instead of py-solc-x: py-solc-x fetches solc binaries
 * from binaries.soliditylang.org, which is blocked in locked-down/offline dev
 * environments. The "solc" npm package ships the compiler itself, so this
 * only needs the npm registry (or works fully offline once installed).
 *
 * Usage: node scripts/compile.js
 */
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const CONTRACT_PATH = path.join(__dirname, "..", "contracts", "EvidenceRegistry.sol");
const OUT_PATH = path.join(__dirname, "..", "build", "EvidenceRegistry.json");

function main() {
  const source = fs.readFileSync(CONTRACT_PATH, "utf8");

  const input = {
    language: "Solidity",
    sources: {
      "EvidenceRegistry.sol": { content: source },
    },
    settings: {
      outputSelection: {
        "*": {
          "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"],
        },
      },
      optimizer: { enabled: true, runs: 200 },
    },
  };

  const output = JSON.parse(solc.compile(JSON.stringify(input)));

  const errors = (output.errors || []).filter((e) => e.severity === "error");
  if (errors.length) {
    console.error("Solidity compilation failed:");
    for (const e of errors) console.error(e.formattedMessage);
    process.exit(1);
  }

  const contract = output.contracts["EvidenceRegistry.sol"]["EvidenceRegistry"];
  const artifact = {
    contractName: "EvidenceRegistry",
    abi: contract.abi,
    bytecode: "0x" + contract.evm.bytecode.object,
    deployedBytecode: "0x" + contract.evm.deployedBytecode.object,
  };

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify(artifact, null, 2));
  console.log(`Compiled OK -> ${OUT_PATH}`);
}

main();
