.PHONY: help init clean submodules \
       build-rust build-python build-swift build-kotlin build-all \
       clean-rust clean-python clean-swift clean-kotlin clean-all \
       test-rust test-python test-swift test-kotlin test-all \
       parity bench \
       tickets ticket-stats

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

MT := python3 tickets/mt/muontickets/muontickets/mt.py

# --- Init & Submodules ---

init: submodules ## Initialize project (submodules + ticket system)
	$(MT) init

submodules: ## Update git submodules
	git submodule update --init --recursive --depth 1

# --- Rust ---

build-rust: ## Build Rust port
	cd port/rust && cargo build

test-rust: ## Test Rust port
	cd port/rust && cargo test

clean-rust: ## Clean Rust build artifacts
	cd port/rust && cargo clean

# --- Python ---

build-python: ## Install Python port dependencies
	cd port/python && uv sync

test-python: ## Test Python port
	cd port/python && uv run pytest

clean-python: ## Clean Python port artifacts
	find port/python -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf port/python/.venv

# --- Swift ---

build-swift: ## Build Swift port
	cd port/swift && swift build

test-swift: ## Test Swift port
	cd port/swift && swift test

clean-swift: ## Clean Swift build artifacts
	cd port/swift && swift package clean

# --- Kotlin ---

build-kotlin: ## Build Kotlin port
	cd port/kotlin && ./gradlew build

test-kotlin: ## Test Kotlin port
	cd port/kotlin && ./gradlew test

clean-kotlin: ## Clean Kotlin build artifacts
	cd port/kotlin && ./gradlew clean

# --- Aggregate ---

build-all: build-rust build-python build-swift build-kotlin ## Build all ports

test-all: test-rust test-python test-swift test-kotlin ## Test all ports

clean-all: clean-rust clean-python clean-swift clean-kotlin ## Clean all port artifacts

# --- Parity & Benchmarks ---

parity: ## Run parity tests across all ports
	@echo "TODO: implement parity test runner in testing/parity/"

bench: ## Run benchmarks across all ports
	@echo "TODO: implement benchmark runner in testing/benchmarks/"

# --- Tickets ---

tickets: ## List open tickets
	$(MT) ls

ticket-stats: ## Show ticket board stats
	$(MT) stats

# --- Cleanup ---

clean: ## Clean tmp/ and common artifacts
	rm -rf tmp/*
	touch tmp/.gitkeep
	@echo "Cleaned tmp/"
