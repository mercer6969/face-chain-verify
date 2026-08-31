// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title EvidenceRegistry
/// @notice Stores an immutable, tamper-evident record (hash + URL) for a piece of
///         off-chain evidence (here: a matched social media post found during a
///         reverse-image face search). Anyone can store a record; anyone can read
///         one back. The chain itself never stores the post content or the image —
///         only its cryptographic fingerprint — so this contract proves that a
///         given payload existed and was unmodified at a given time, without ever
///         holding the underlying personal data on-chain.
contract EvidenceRegistry {
    struct Record {
        bool exists;
        uint256 timestamp; // block timestamp at submission
        address submitter; // msg.sender that submitted the record
        string postUrl;    // URL of the matched post (for human reference only)
    }

    // postHash => Record. postHash = keccak256(canonical JSON metadata || image bytes)
    mapping(bytes32 => Record) private records;

    event RecordStored(
        bytes32 indexed postHash,
        address indexed submitter,
        uint256 timestamp,
        string postUrl
    );

    /// @notice Notarize a new piece of evidence on-chain.
    /// @param _postHash keccak256 digest of the normalized post metadata + image bytes.
    /// @param _postUrl  URL of the source post, kept for human-readable reference.
    function storeRecord(bytes32 _postHash, string calldata _postUrl) external {
        require(_postHash != bytes32(0), "EvidenceRegistry: empty hash");
        require(!records[_postHash].exists, "EvidenceRegistry: record already exists");

        records[_postHash] = Record({
            exists: true,
            timestamp: block.timestamp,
            submitter: msg.sender,
            postUrl: _postUrl
        });

        emit RecordStored(_postHash, msg.sender, block.timestamp, _postUrl);
    }

    /// @notice Verify whether a given hash matches a previously stored record.
    /// @dev    This is the core tamper-detection primitive: recompute the hash of
    ///         your local data and pass it in here. If a single byte of the post
    ///         text, metadata, or image changed, the recomputed hash will not match
    ///         any stored record and isValid will be false.
    /// @param _postHash keccak256 digest to check.
    /// @return isValid   true if a record with this exact hash exists on-chain.
    /// @return timestamp block timestamp the record was stored at (0 if none).
    /// @return submitter address that stored the record (address(0) if none).
    function verifyRecord(bytes32 _postHash)
        external
        view
        returns (bool isValid, uint256 timestamp, address submitter)
    {
        Record storage r = records[_postHash];
        return (r.exists, r.timestamp, r.submitter);
    }

    /// @notice Convenience getter for the stored post URL of a known-good hash.
    function getPostUrl(bytes32 _postHash) external view returns (string memory) {
        require(records[_postHash].exists, "EvidenceRegistry: no such record");
        return records[_postHash].postUrl;
    }
}
