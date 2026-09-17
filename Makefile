include config/config.mk

.DEFAULT_GOAL := help

# OS and Architecture Detection
DETECTED_OS := $(shell uname -s)
DETECTED_ARCH := $(shell uname -m)

# CI Detection
CI ?= false

# Automated prerequisite installation (set to false in check-prerequisites for read-only probe)
AUTO_INSTALL ?= true

# Options passed to build_image.sh (use --output-log in CI environments)
ifeq ($(CI),true)
BUILD_IMAGE_ARGS ?= --output-log
else
BUILD_IMAGE_ARGS ?=
endif

# Terminal Colors (disabled in CI or when NO_COLOR is set)
ifeq ($(CI),true)
COLOR_BOLD :=
COLOR_GREEN :=
COLOR_RED :=
COLOR_YELLOW :=
COLOR_RESET :=
else ifdef NO_COLOR
COLOR_BOLD :=
COLOR_GREEN :=
COLOR_RED :=
COLOR_YELLOW :=
COLOR_RESET :=
else
COLOR_BOLD := \033[1m
COLOR_GREEN := \033[1;32m
COLOR_RED := \033[1;31m
COLOR_YELLOW := \033[1;33m
COLOR_RESET := \033[0m
endif

.PHONY: check-prerequisites prerequisites check-docker install-docker install-homebrew install-miniforge create-conda-env activate-conda-env build-image help

## ==============================================================================
## Docker & Prerequisite Installation & Checks
## ==============================================================================

# Install Homebrew if not installed (macOS)
install-homebrew:
	@if [ "$(DETECTED_OS)" = "Darwin" ]; then \
		if ! command -v brew >/dev/null 2>&1; then \
			echo "Homebrew not found. Installing Homebrew..."; \
			NONINTERACTIVE=1 /bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || exit 1; \
		else \
			echo "Homebrew is already installed."; \
		fi; \
	fi

# Install Docker based on operating system
install-docker:
	@echo "$(COLOR_BOLD)Checking Docker installation for $(DETECTED_OS)...$(COLOR_RESET)"
	@if [ -n "$(findstring n,$(firstword -$(MAKEFLAGS)))" ]; then exit 0; \
	elif command -v docker >/dev/null 2>&1; then \
		echo "$(COLOR_GREEN)✅ Docker is already installed: $$(docker --version)$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  Docker not found. Installing Docker for $(DETECTED_OS)...$(COLOR_RESET)"; \
		if [ "$(DETECTED_OS)" = "Darwin" ]; then \
			if ! command -v brew >/dev/null 2>&1; then \
				$(MAKE) install-homebrew || exit 1; \
			fi; \
			echo "Detected macOS - installing Docker Desktop via Homebrew..."; \
			brew install --cask docker || exit 1; \
			echo "$(COLOR_GREEN)✅ Docker installed successfully.$(COLOR_RESET)"; \
			echo "Please open Docker Desktop to complete initialization."; \
		elif [ "$(DETECTED_OS)" = "Linux" ]; then \
			echo "Detected Linux - installing Docker via get.docker.com..."; \
			TMP_SCRIPT=$$(mktemp /tmp/get-docker-XXXXXX.sh); \
			curl -fsSL https://get.docker.com -o "$$TMP_SCRIPT" || { echo "$(COLOR_RED)❌ Failed to download Docker installer$(COLOR_RESET)"; rm -f "$$TMP_SCRIPT"; exit 1; }; \
			sudo sh "$$TMP_SCRIPT" || { echo "$(COLOR_RED)❌ Docker installation failed$(COLOR_RESET)"; rm -f "$$TMP_SCRIPT"; exit 1; }; \
			rm -f "$$TMP_SCRIPT"; \
			if command -v systemctl >/dev/null 2>&1; then \
				sudo systemctl enable --now docker 2>/dev/null || true; \
			elif command -v service >/dev/null 2>&1; then \
				sudo service docker start 2>/dev/null || true; \
			fi; \
			sudo usermod -aG docker $$USER 2>/dev/null || true; \
			echo "$(COLOR_GREEN)✅ Docker installed successfully.$(COLOR_RESET)"; \
			echo "$(COLOR_YELLOW)⚠️  Please log out and log back in, or run $(COLOR_BOLD)newgrp docker$(COLOR_RESET) to use Docker without sudo."; \
		else \
			echo "$(COLOR_RED)❌ Unsupported operating system: $(DETECTED_OS)$(COLOR_RESET)"; \
			exit 1; \
		fi; \
	fi

# Check Docker prerequisite (CLI, buildx, daemon) and install Docker if missing
check-docker:
	@if [ -n "$(findstring n,$(firstword -$(MAKEFLAGS)))" ]; then exit 0; fi; \
	ERRORS=0; \
	printf "%-32s " "Checking Docker CLI..."; \
	if ! command -v docker >/dev/null 2>&1; then \
		if [ "$(AUTO_INSTALL)" = "true" ]; then \
			echo "$(COLOR_YELLOW)⚠️  Docker CLI not found. Installing Docker...$(COLOR_RESET)"; \
			$(MAKE) install-docker || { echo "$(COLOR_RED)❌ Docker installation failed$(COLOR_RESET)"; ERRORS=$$((ERRORS + 1)); }; \
		fi; \
	fi; \
	if command -v docker >/dev/null 2>&1; then \
		DOCKER_VER=$$(docker --version 2>/dev/null); \
		echo "$(COLOR_GREEN)✅ Found: $$DOCKER_VER$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_RED)❌ Missing: Docker CLI not found$(COLOR_RESET)"; \
		echo "   Run $(COLOR_BOLD)make check-docker$(COLOR_RESET) or $(COLOR_BOLD)make install-docker$(COLOR_RESET) to install."; \
		ERRORS=$$((ERRORS + 1)); \
	fi; \
	\
	printf "%-32s " "Checking Docker Buildx..."; \
	if docker buildx version >/dev/null 2>&1; then \
		BUILDX_VER=$$(docker buildx version 2>/dev/null); \
		echo "$(COLOR_GREEN)✅ Found: $$BUILDX_VER$(COLOR_RESET)"; \
	else \
		if [ "$(AUTO_INSTALL)" = "true" ]; then \
			echo "$(COLOR_YELLOW)⚠️  Docker Buildx plugin not found. Attempting installation...$(COLOR_RESET)"; \
			if [ "$(DETECTED_OS)" = "Darwin" ]; then \
				if command -v brew >/dev/null 2>&1; then \
					brew install docker-buildx 2>/dev/null || true; \
				fi; \
			elif [ "$(DETECTED_OS)" = "Linux" ]; then \
				if command -v apt-get >/dev/null 2>&1; then \
					sudo apt-get update -qq && sudo apt-get install -y docker-buildx-plugin 2>/dev/null || true; \
				fi; \
			fi; \
			if docker buildx version >/dev/null 2>&1; then \
				BUILDX_VER=$$(docker buildx version 2>/dev/null); \
				echo "$(COLOR_GREEN)✅ Found: $$BUILDX_VER$(COLOR_RESET)"; \
			else \
				echo "$(COLOR_RED)❌ Missing: Docker Buildx plugin not found$(COLOR_RESET)"; \
				ERRORS=$$((ERRORS + 1)); \
			fi; \
		else \
			echo "$(COLOR_RED)❌ Missing: Docker Buildx plugin not found$(COLOR_RESET)"; \
			echo "   Run $(COLOR_BOLD)make check-docker$(COLOR_RESET) to install."; \
			ERRORS=$$((ERRORS + 1)); \
		fi; \
	fi; \
	\
	printf "%-32s " "Checking Docker daemon status..."; \
	if docker info >/dev/null 2>&1; then \
		echo "$(COLOR_GREEN)✅ Running$(COLOR_RESET)"; \
	else \
		if [ "$(AUTO_INSTALL)" = "true" ]; then \
			echo "$(COLOR_YELLOW)⚠️  Docker daemon stopped. Attempting to start...$(COLOR_RESET)"; \
			if [ "$(DETECTED_OS)" = "Darwin" ]; then \
				open -a Docker 2>/dev/null || open -a "Docker Desktop" 2>/dev/null || true; \
			else \
				if command -v systemctl >/dev/null 2>&1; then \
					sudo systemctl start docker 2>/dev/null || true; \
				elif command -v service >/dev/null 2>&1; then \
					sudo service docker start 2>/dev/null || true; \
				fi; \
			fi; \
			for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
				if docker info >/dev/null 2>&1; then \
					break; \
				fi; \
				sleep 1; \
			done; \
			if docker info >/dev/null 2>&1; then \
				echo "$(COLOR_GREEN)✅ Docker daemon running$(COLOR_RESET)"; \
			else \
				echo "$(COLOR_RED)❌ Stopped: Docker daemon is not running$(COLOR_RESET)"; \
				if [ "$(DETECTED_OS)" = "Darwin" ]; then \
					echo "   Please start Docker Desktop manually (open -a Docker)"; \
				else \
					echo "   Please start Docker daemon: sudo systemctl start docker"; \
				fi; \
				ERRORS=$$((ERRORS + 1)); \
			fi; \
		else \
			echo "$(COLOR_RED)❌ Stopped: Docker daemon is not running$(COLOR_RESET)"; \
			if [ "$(DETECTED_OS)" = "Darwin" ]; then \
				echo "   Please start Docker Desktop manually (open -a Docker) or run $(COLOR_BOLD)make check-docker$(COLOR_RESET)."; \
			else \
				echo "   Please start Docker daemon: sudo systemctl start docker or run $(COLOR_BOLD)make check-docker$(COLOR_RESET)."; \
			fi; \
			ERRORS=$$((ERRORS + 1)); \
		fi; \
	fi; \
	if [ $$ERRORS -gt 0 ]; then \
		exit 1; \
	fi

# Check system prerequisites: Docker (CLI, buildx, daemon) and Conda
check-prerequisites:
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) Checking Prerequisites for holon-coherence$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) OS: $(DETECTED_OS) | Arch: $(DETECTED_ARCH)$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@if [ -n "$(findstring n,$(firstword -$(MAKEFLAGS)))" ]; then exit 0; fi; \
	ERRORS=0; \
	$(MAKE) check-docker AUTO_INSTALL=false || ERRORS=$$((ERRORS + 1)); \
	printf "%-32s " "Checking Conda..."; \
	$(FIND_CONDA_BIN); \
	if [ -n "$$CONDA_BIN" ]; then \
		CONDA_VER=$$("$$CONDA_BIN" --version 2>/dev/null); \
		echo "$(COLOR_GREEN)✅ Found: $$CONDA_VER ($$CONDA_BIN)$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_RED)❌ Missing: Conda not found$(COLOR_RESET)"; \
		echo "   Run $(COLOR_BOLD)make create-conda-env$(COLOR_RESET) or $(COLOR_BOLD)make install-miniforge$(COLOR_RESET) to install automatically."; \
		ERRORS=$$((ERRORS + 1)); \
	fi; \
	\
	echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"; \
	if [ $$ERRORS -gt 0 ]; then \
		echo "$(COLOR_RED)❌ $$ERRORS prerequisite check(s) failed. Please install or start the required tools above.$(COLOR_RESET)"; \
		exit 1; \
	else \
		echo "$(COLOR_GREEN)✅ All prerequisites are satisfied!$(COLOR_RESET)"; \
	fi

# Alias for check-prerequisites
prerequisites: check-prerequisites

# Install Miniforge based on operating system
install-miniforge:
	@echo "$(COLOR_BOLD)Installing Miniforge for $(DETECTED_OS)...$(COLOR_RESET)"
	@if [ -n "$(findstring n,$(firstword -$(MAKEFLAGS)))" ]; then exit 0; fi; \
	$(FIND_CONDA_BIN); \
	if [ -n "$$CONDA_BIN" ]; then \
		echo "$(COLOR_GREEN)✅ Miniforge is already installed ($$CONDA_BIN).$(COLOR_RESET)"; \
	elif [ "$(DETECTED_OS)" = "Darwin" ]; then \
		if ! command -v brew >/dev/null 2>&1; then \
			$(MAKE) install-homebrew || exit 1; \
		fi; \
		if brew list --cask miniforge >/dev/null 2>&1; then \
			echo "$(COLOR_GREEN)✅ Miniforge is already installed.$(COLOR_RESET)"; \
		else \
			echo "Detected macOS - installing via Homebrew..."; \
			brew install --cask miniforge || exit 1; \
			echo "$(COLOR_GREEN)✅ Miniforge installed successfully$(COLOR_RESET)"; \
			echo "Please restart your terminal or run $(COLOR_BOLD)conda init$(COLOR_RESET) for your shell."; \
		fi; \
	elif [ "$(DETECTED_OS)" = "Linux" ]; then \
		echo "Detected Linux - detecting architecture..."; \
		ARCH=$$(uname -m); \
		case "$$ARCH" in \
			x86_64) MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh";; \
			aarch64) MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh";; \
			*) echo "$(COLOR_RED)❌ Unsupported Linux architecture: $$ARCH$(COLOR_RESET)"; exit 1;; \
		esac; \
		if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then \
			echo "$(COLOR_RED)❌ Neither curl nor wget found. Please install curl or wget.$(COLOR_RESET)"; \
			exit 1; \
		fi; \
		TMP_SCRIPT=$$(mktemp /tmp/miniforge-XXXXXX.sh); \
		if command -v curl >/dev/null 2>&1; then \
			TAG=$$(curl -sI "$$MINIFORGE_URL" | grep -i '^location:' | sed -n 's|.*/releases/download/\([^/]*\)/.*|\1|p' | tr -d '\r'); \
			curl -fsSL "$$MINIFORGE_URL" -o "$$TMP_SCRIPT"; \
			[ -n "$$TAG" ] && EXPECTED_SHA=$$(curl -fsSL "https://github.com/conda-forge/miniforge/releases/download/$${TAG}/Miniforge3-$${TAG}-Linux-$${ARCH}.sh.sha256" | awk '{print $$1}'); \
		else \
			TAG=$$(wget --spider -S "$$MINIFORGE_URL" 2>&1 | grep -i 'Location:' | sed -n 's|.*/releases/download/\([^/]*\)/.*|\1|p' | tail -n 1 | tr -d '\r'); \
			wget "$$MINIFORGE_URL" -O "$$TMP_SCRIPT"; \
			[ -n "$$TAG" ] && EXPECTED_SHA=$$(wget -qO- "https://github.com/conda-forge/miniforge/releases/download/$${TAG}/Miniforge3-$${TAG}-Linux-$${ARCH}.sh.sha256" | awk '{print $$1}'); \
		fi; \
		if [ -z "$$EXPECTED_SHA" ]; then \
			echo "$(COLOR_RED)❌ Failed to retrieve expected checksum for Miniforge$(COLOR_RESET)"; \
			rm -f "$$TMP_SCRIPT"; \
			exit 1; \
		fi; \
		if command -v sha256sum >/dev/null 2>&1; then \
			ACTUAL_SHA=$$(sha256sum "$$TMP_SCRIPT" | awk '{print $$1}'); \
		elif command -v shasum >/dev/null 2>&1; then \
			ACTUAL_SHA=$$(shasum -a 256 "$$TMP_SCRIPT" | awk '{print $$1}'); \
		else \
			echo "$(COLOR_RED)❌ Neither sha256sum nor shasum found for verification$(COLOR_RESET)"; \
			rm -f "$$TMP_SCRIPT"; \
			exit 1; \
		fi; \
		if [ "$$EXPECTED_SHA" != "$$ACTUAL_SHA" ]; then \
			echo "$(COLOR_RED)❌ Checksum verification failed$(COLOR_RESET)"; \
			rm -f "$$TMP_SCRIPT"; \
			exit 1; \
		fi; \
		echo "Installing Miniforge to $$HOME/miniforge3..."; \
		bash "$$TMP_SCRIPT" -b -u -p $$HOME/miniforge3 || { echo "$(COLOR_RED)❌ Miniforge installation failed$(COLOR_RESET)"; rm -f "$$TMP_SCRIPT"; exit 1; }; \
		rm -f "$$TMP_SCRIPT"; \
		echo "$(COLOR_GREEN)✅ Miniforge installed successfully$(COLOR_RESET)"; \
		echo "Please restart your terminal or run $(COLOR_BOLD)conda init$(COLOR_RESET) for your shell."; \
	else \
		echo "$(COLOR_RED)❌ Unsupported operating system: $(DETECTED_OS)$(COLOR_RESET)"; \
		exit 1; \
	fi

# Create conda environment 'holon' from environment.yml
create-conda-env: install-miniforge
	@echo "$(COLOR_BOLD)Creating conda environment 'holon' from environment.yml...$(COLOR_RESET)"
	@$(FIND_CONDA_BIN); \
	if [ -z "$$CONDA_BIN" ]; then \
		echo "$(COLOR_RED)❌ Conda not found after Miniforge installation.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	if "$$CONDA_BIN" env list | grep -q -E '^[[:space:]]*holon[[:space:]]+'; then \
		echo "$(COLOR_GREEN)✅ Environment 'holon' already exists.$(COLOR_RESET)"; \
	else \
		echo "Creating new environment 'holon'..."; \
		"$$CONDA_BIN" env create -n holon -f environment.yml; \
		echo "$(COLOR_GREEN)✅ Environment 'holon' created successfully.$(COLOR_RESET)"; \
	fi; \
	echo "To activate the environment, run:"; \
	echo "  conda activate holon"

# Activate conda environment command helper
activate-conda-env:
	@echo "To activate the environment, run the following command:"
	@echo "  conda activate holon"

## ==============================================================================
## Docker Image Build
## ==============================================================================

# Build the holon-coherence Docker container image
build-image: check-docker
	@echo "$(COLOR_BOLD)Building holon-coherence Docker image...$(COLOR_RESET)"
	@./build_image.sh $(BUILD_IMAGE_ARGS)


## ==============================================================================
## Help Target
## ==============================================================================

# Show this help message
help:
	@echo "$(COLOR_BOLD)Usage:$(COLOR_RESET) make [target]"
	@echo "All targets must be executed from the root of the repository."
	@echo ""
	@echo "$(COLOR_BOLD)Available targets:$(COLOR_RESET)"
	@printf $(HELP_FORMAT) "check-prerequisites" "Check Docker (CLI, buildx, daemon) and Conda dependencies."
	@printf $(HELP_FORMAT) "prerequisites" "Alias for check-prerequisites."
	@printf $(HELP_FORMAT) "check-docker" "Check Docker prerequisite and install Docker if missing."
	@printf $(HELP_FORMAT) "install-docker" "Install Docker for the detected operating system."
	@printf $(HELP_FORMAT) "install-homebrew" "Install Homebrew (macOS only)."
	@printf $(HELP_FORMAT) "install-miniforge" "Install Miniforge for the detected operating system."
	@printf $(HELP_FORMAT) "create-conda-env" "Create the 'holon' Conda environment from environment.yml."
	@printf $(HELP_FORMAT) "activate-conda-env" "Show command to activate the 'holon' Conda environment."
	@printf $(HELP_FORMAT) "build-image" "Build the holon-coherence Docker container via build_image.sh."
	@printf $(HELP_FORMAT) "help" "Show this help message."
	@echo ""
