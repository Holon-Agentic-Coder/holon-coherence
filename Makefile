include config/config.mk

.DEFAULT_GOAL := help

# OS and Architecture Detection
DETECTED_OS := $(shell uname -s)
DETECTED_ARCH := $(shell uname -m)

# CI Detection
CI ?= false

# Automated prerequisite installation (set to false in check-prerequisites for read-only probe)
AUTO_INSTALL ?= true

# Conda Environment Configuration.
#
# CONDA_ENV is the *read* default used when reporting prerequisites: reporting
# the active environment is the most useful thing, so default it to
# CONDA_DEFAULT_ENV when one is active, else holon.
ifdef CONDA_DEFAULT_ENV
CONDA_ENV ?= $(CONDA_DEFAULT_ENV)
else
CONDA_ENV ?= holon
endif

# CONDA_WRITE_ENV is the *write* target used by create-conda-env. It never
# follows the active environment: an activated `base` is not consent to install
# packages into base. It defaults to holon and tracks CONDA_ENV only when that
# value was requested explicitly (command line or exported environment).
#
# CONDA_BASE_CONSENT is true only when `base` was requested up front; otherwise
# create-conda-env asks for a typed `yes` interactively and refuses in
# non-interactive runs.
CONDA_ENV_ORIGIN := $(origin CONDA_ENV)
CONDA_ENV_REQUESTED := $(if $(or $(findstring command line,$(CONDA_ENV_ORIGIN)),$(findstring environment,$(CONDA_ENV_ORIGIN))),true,false)
ifeq ($(CONDA_ENV_REQUESTED),true)
CONDA_WRITE_ENV := $(CONDA_ENV)
else
CONDA_WRITE_ENV := holon
endif
CONDA_BASE_CONSENT := false
ifeq ($(CONDA_WRITE_ENV),base)
ifeq ($(CONDA_ENV_REQUESTED),true)
CONDA_BASE_CONSENT := true
endif
endif

# Pruning an environment this target did not create can remove packages the
# user added by hand, so it is opt-in: pass CONDA_PRUNE=1 (or true).
CONDA_PRUNE ?= false

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
	@if [ -n "$(findstring n,$(foreach w,$(MAKEFLAGS),$(if $(findstring =,$(w)),,$(filter-out --%,$(w)))))" ]; then exit 0; \
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
	@if [ -n "$(findstring n,$(foreach w,$(MAKEFLAGS),$(if $(findstring =,$(w)),,$(filter-out --%,$(w)))))" ]; then exit 0; fi; \
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

# Check system prerequisites: Docker (CLI, buildx, daemon), Conda, uv, OpenSSL, and npx
check-prerequisites:
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) Checking Prerequisites for holon-coherence$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) OS: $(DETECTED_OS) | Arch: $(DETECTED_ARCH)$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@if [ -n "$(findstring n,$(foreach w,$(MAKEFLAGS),$(if $(findstring =,$(w)),,$(filter-out --%,$(w)))))" ]; then exit 0; fi; \
	ERRORS=0; \
	WARNINGS=0; \
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
	printf "%-32s " "Checking uv in Conda env..."; \
	TARGET_ENV="$(CONDA_ENV)"; \
	ACTIVE_ENV="$$CONDA_DEFAULT_ENV"; \
	if [ -n "$$ACTIVE_ENV" ]; then ACTIVE_DESC="active env: $$ACTIVE_ENV"; else ACTIVE_DESC="no active conda env"; fi; \
	UV_KIND=""; UV_BIN=""; UV_WHERE=""; ENV_PREFIX=""; \
	if [ -n "$$CONDA_PREFIX" ] && [ -x "$$CONDA_PREFIX/bin/uv" ]; then \
		UV_KIND=env; UV_BIN="$$CONDA_PREFIX/bin/uv"; UV_WHERE="conda env $${ACTIVE_ENV:-$$CONDA_PREFIX}"; \
	fi; \
	if [ -z "$$UV_KIND" ] && [ -n "$$CONDA_BIN" ]; then \
		ENV_PREFIX=$$("$$CONDA_BIN" env list 2>/dev/null | awk -v env="$$TARGET_ENV" '$$1 == env { line = $$0; sub(/^[ \t]*[^ \t]+[ \t]+/, "", line); sub(/^[*+ \t]+/, "", line); sub(/[ \t\r]*[*+][ \t\r]*$$/, "", line); sub(/[ \t\r]+$$/, "", line); print line; exit }'); \
		if [ -n "$$ENV_PREFIX" ] && [ -x "$$ENV_PREFIX/bin/uv" ]; then \
			UV_KIND=env; UV_BIN="$$ENV_PREFIX/bin/uv"; UV_WHERE="conda env $$TARGET_ENV ($$ENV_PREFIX)"; \
		fi; \
	fi; \
	if [ -z "$$UV_KIND" ] && command -v uv >/dev/null 2>&1; then \
		UV_KIND=path; UV_BIN=$$(command -v uv); \
	fi; \
	if [ "$$UV_KIND" = "env" ]; then \
		UV_VER=$$("$$UV_BIN" --version 2>/dev/null); \
		echo "$(COLOR_GREEN)✅ Found: $$UV_VER (uv inside $$UV_WHERE)$(COLOR_RESET)"; \
	elif [ "$$UV_KIND" = "path" ]; then \
		UV_VER=$$("$$UV_BIN" --version 2>/dev/null); \
		echo "$(COLOR_YELLOW)⚠️  Found on PATH only: $$UV_VER ($$UV_BIN)$(COLOR_RESET)"; \
		echo "   uv is NOT installed in conda env '$$TARGET_ENV' ($$ACTIVE_DESC); this resolution came from PATH."; \
		echo "   Run $(COLOR_BOLD)make create-conda-env CONDA_ENV=$$TARGET_ENV$(COLOR_RESET) to install it into the environment."; \
		WARNINGS=$$((WARNINGS + 1)); \
	else \
		echo "$(COLOR_RED)❌ Missing: uv not found on PATH or in conda env '$$TARGET_ENV' ($$ACTIVE_DESC)$(COLOR_RESET)"; \
		echo "   Run $(COLOR_BOLD)make create-conda-env$(COLOR_RESET) or $(COLOR_BOLD)make create-conda-env CONDA_ENV=$$TARGET_ENV$(COLOR_RESET)."; \
		ERRORS=$$((ERRORS + 1)); \
	fi; \
	\
	printf "%-32s " "Checking OpenSSL..."; \
	if command -v openssl >/dev/null 2>&1; then \
		OPENSSL_VER=$$(openssl version 2>/dev/null || true); \
		echo "$(COLOR_GREEN)✅ Found: $$OPENSSL_VER$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_RED)❌ Missing: openssl not found$(COLOR_RESET)"; \
		echo "   OpenSSL is required by ca_generator.py for Root CA generation."; \
		if [ "$(DETECTED_OS)" = "Darwin" ]; then \
			echo "   Install via Homebrew: brew install openssl"; \
		else \
			echo "   Install via package manager: sudo apt install openssl"; \
		fi; \
		ERRORS=$$((ERRORS + 1)); \
	fi; \
	\
	printf "%-32s " "Checking npx (Prettier)..."; \
	if command -v npx >/dev/null 2>&1; then \
		NPX_VER=$$(npx --version 2>/dev/null || true); \
		echo "$(COLOR_GREEN)✅ Found: npx v$$NPX_VER$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  Missing: npx not found$(COLOR_RESET)"; \
		echo "   npx is required for Prettier markdown documentation hygiene checks."; \
		WARNINGS=$$((WARNINGS + 1)); \
	fi; \
	\
	echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"; \
	if [ $$ERRORS -gt 0 ]; then \
		echo "$(COLOR_RED)❌ $$ERRORS prerequisite check(s) failed. Please install or start the required tools above.$(COLOR_RESET)"; \
		exit 1; \
	elif [ $$WARNINGS -gt 0 ]; then \
		echo "$(COLOR_YELLOW)⚠️  Core prerequisites satisfied, but $$WARNINGS optional/advisory check(s) raised warnings.$(COLOR_RESET)"; \
		exit 0; \
	else \
		echo "$(COLOR_GREEN)✅ All prerequisites are satisfied!$(COLOR_RESET)"; \
	fi

# Alias for check-prerequisites
prerequisites: check-prerequisites

# Install Miniforge based on operating system
install-miniforge:
	@echo "$(COLOR_BOLD)Installing Miniforge for $(DETECTED_OS)...$(COLOR_RESET)"
	@if [ -n "$(findstring n,$(foreach w,$(MAKEFLAGS),$(if $(findstring =,$(w)),,$(filter-out --%,$(w)))))" ]; then exit 0; fi; \
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

# Create or update conda environment with interactive confirmation/selection
create-conda-env: install-miniforge
	@$(FIND_CONDA_BIN); \
	if [ -z "$$CONDA_BIN" ]; then \
		echo "$(COLOR_RED)❌ Conda not found after Miniforge installation.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	CHOSEN_ENV="$(CONDA_WRITE_ENV)"; \
	BASE_CONSENT="$(CONDA_BASE_CONSENT)"; \
	ACTIVE_ENV="$$CONDA_DEFAULT_ENV"; \
	if [ -n "$$ACTIVE_ENV" ]; then ACTIVE_DESC="active env: $$ACTIVE_ENV"; else ACTIVE_DESC="no active conda env"; fi; \
	if [ -t 0 ] && [ "$(CI)" != "true" ] && [ "$(NONINTERACTIVE)" != "1" ]; then \
		echo "$(COLOR_BOLD)====================================================$(COLOR_RESET)"; \
		echo " Holon-Coherence Conda Environment Setup"; \
		echo "$(COLOR_BOLD)====================================================$(COLOR_RESET)"; \
		echo "This will install Python and uv via Conda into the chosen environment."; \
		echo " Currently active: $$ACTIVE_DESC (press Enter to keep '$$CHOSEN_ENV')"; \
		printf "Enter target environment name [default: %s]: " "$$CHOSEN_ENV"; \
		read -r USER_INPUT; \
		if [ -n "$$USER_INPUT" ]; then \
			CHOSEN_ENV="$$USER_INPUT"; \
		fi; \
		if [ "$$CHOSEN_ENV" = "base" ] && [ "$$BASE_CONSENT" != "true" ]; then \
			printf "'base' is a shared environment. Type 'yes' to install into it [no]: "; \
			read -r BASE_REPLY; \
			if [ "$$BASE_REPLY" = "yes" ]; then \
				BASE_CONSENT=true; \
			else \
				echo "Aborted: 'base' was not confirmed. Pick another name or pass $(COLOR_BOLD)CONDA_ENV=base$(COLOR_RESET) deliberately."; \
				exit 1; \
			fi; \
		fi; \
	fi; \
	if [ -z "$$CHOSEN_ENV" ]; then \
		echo "$(COLOR_RED)❌ Empty environment name. Pass $(COLOR_BOLD)CONDA_ENV=<name>$(COLOR_RESET) or use the default 'holon'.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	if [ "$$CHOSEN_ENV" = "base" ] && [ "$$BASE_CONSENT" != "true" ]; then \
		echo "$(COLOR_RED)❌ Refusing to write to 'base': it was not explicitly requested.$(COLOR_RESET)"; \
		echo "   Request it deliberately: make create-conda-env $(COLOR_BOLD)CONDA_ENV=base$(COLOR_RESET)"; \
		echo "   Or use a dedicated environment: make create-conda-env $(COLOR_BOLD)CONDA_ENV=holon$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	echo "$(COLOR_BOLD)Setting up Conda environment '$$CHOSEN_ENV' ($$ACTIVE_DESC)...$(COLOR_RESET)"; \
	if [ "$$CHOSEN_ENV" = "base" ]; then \
		echo "Installing uv and python into 'base' conda environment..."; \
		echo "$(COLOR_YELLOW)⚠️  The 'base' route installs a narrower package set (uv, python=3.13) than environment.yml.$(COLOR_RESET)"; \
		"$$CONDA_BIN" install -y -n base -c conda-forge uv python=3.13 || exit 1; \
		echo "$(COLOR_GREEN)✅ 'base' environment updated with uv and python=3.13.$(COLOR_RESET)"; \
	else \
		if "$$CONDA_BIN" env list 2>/dev/null | awk -v env="$$CHOSEN_ENV" '$$1 == env { found = 1; exit } END { exit !found }'; then \
			echo "Environment '$$CHOSEN_ENV' already exists. Updating environment..."; \
			CONDA_PRUNE_FLAG=""; \
			if [ "$(CONDA_PRUNE)" = "1" ] || [ "$(CONDA_PRUNE)" = "true" ]; then \
				CONDA_PRUNE_FLAG="--prune"; \
				echo "CONDA_PRUNE=$(CONDA_PRUNE): pruning packages that are absent from environment.yml."; \
			fi; \
			"$$CONDA_BIN" env update -n "$$CHOSEN_ENV" -f environment.yml $$CONDA_PRUNE_FLAG || exit 1; \
			echo "$(COLOR_GREEN)✅ Environment '$$CHOSEN_ENV' updated successfully.$(COLOR_RESET)"; \
		else \
			echo "Creating new environment '$$CHOSEN_ENV' from environment.yml..."; \
			"$$CONDA_BIN" env create -n "$$CHOSEN_ENV" -f environment.yml || exit 1; \
			echo "$(COLOR_GREEN)✅ Environment '$$CHOSEN_ENV' created successfully.$(COLOR_RESET)"; \
		fi; \
	fi; \
	echo "To activate the environment, run:"; \
	if [ "$$CHOSEN_ENV" = "$$ACTIVE_ENV" ]; then \
		echo "  conda activate $$CHOSEN_ENV  (already active: $$ACTIVE_ENV)"; \
	else \
		echo "  conda activate $$CHOSEN_ENV"; \
	fi

# Activate conda environment command helper
activate-conda-env:
	@echo "Target conda environment: $(CONDA_WRITE_ENV)"
	@if [ -n "$$CONDA_DEFAULT_ENV" ]; then \
		echo "Currently active conda environment: $$CONDA_DEFAULT_ENV"; \
		if [ "$$CONDA_DEFAULT_ENV" = "$(CONDA_WRITE_ENV)" ]; then \
			echo "'$(CONDA_WRITE_ENV)' is already active; nothing to activate."; \
		else \
			echo "To switch to the target environment, run the following command:"; \
			echo "  conda activate $(CONDA_WRITE_ENV)"; \
		fi; \
	else \
		echo "No conda environment is currently active. To activate the target environment, run:"; \
		echo "  conda activate $(CONDA_WRITE_ENV)"; \
	fi

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
	@printf $(HELP_FORMAT) "check-prerequisites" "Check Docker, Conda, uv, OpenSSL, and npx prerequisites."
	@printf $(HELP_FORMAT) "prerequisites" "Alias for check-prerequisites."
	@printf $(HELP_FORMAT) "check-docker" "Check Docker prerequisite and install Docker if missing."
	@printf $(HELP_FORMAT) "install-docker" "Install Docker for the detected operating system."
	@printf $(HELP_FORMAT) "install-homebrew" "Install Homebrew (macOS only)."
	@printf $(HELP_FORMAT) "install-miniforge" "Install Miniforge for the detected operating system."
	@printf $(HELP_FORMAT) "create-conda-env" "Create or update Conda environment (CONDA_WRITE_ENV, default 'holon'; 'base' only when explicitly requested; CONDA_PRUNE=1 to prune)."
	@printf $(HELP_FORMAT) "activate-conda-env" "Show command to activate the Conda environment."
	@printf $(HELP_FORMAT) "build-image" "Build the holon-coherence Docker container via build_image.sh."
	@printf $(HELP_FORMAT) "help" "Show this help message."
	@echo ""
	@echo "$(COLOR_BOLD)Variables:$(COLOR_RESET)"
	@printf $(HELP_FORMAT) "CONDA_ENV" "Environment to report in check-prerequisites (default: active CONDA_DEFAULT_ENV, else 'holon')."
	@printf $(HELP_FORMAT) "CONDA_WRITE_ENV" "Environment create-conda-env writes to (default: 'holon'; follows CONDA_ENV only when passed explicitly, never an activated 'base')."
	@printf $(HELP_FORMAT) "CONDA_PRUNE" "Set to 1 or true to add --prune to 'conda env update' for an existing environment (default: false)."
	@printf $(HELP_FORMAT) "NONINTERACTIVE" "Set to 1 to skip the interactive target prompt (also implied by CI=true or a non-terminal stdin)."
	@echo ""
