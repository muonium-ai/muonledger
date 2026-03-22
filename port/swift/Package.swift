// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "muonledger",
    targets: [
        .executableTarget(name: "muonledger", path: "Sources/MuonLedger"),
        .testTarget(name: "MuonLedgerTests", dependencies: ["muonledger"], path: "Tests/MuonLedgerTests"),
    ]
)
