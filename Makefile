include config/config.mk

.DEFAULT_GOAL := help

DETECTED_OS := $(shell uname -s)
DETECTED_ARCH := $(shell uname -m)

MF_SINGLE_LETTER_OPTIONS := b B c C d D e E f F g G h i I j k l L m n N o p q r R s S t v w W
MF_ALPHANUMERIC := a b c d e f g h i j k l m n o p q r s t u v w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 0 1 2 3 4 5 6 7 8 9

mf_non_option_characters = $(strip $(foreach character,$(MF_ALPHANUMERIC),$(if $(findstring $(character),$(1)),$(if $(filter $(character),$(MF_SINGLE_LETTER_OPTIONS)),,$(character)))))
mf_drop_leading_long_options = $(if $(filter --%,$(firstword $(1))),$(call mf_drop_leading_long_options,$(wordlist 2,$(words $(1)),$(1))),$(1))
mf_drop_leading_assignments = $(if $(findstring =,$(firstword $(1))),$(call mf_drop_leading_assignments,$(wordlist 2,$(words $(1)),$(1))),$(1))

MF_ASSIGNMENT_REGION = $(call mf_drop_leading_assignments,$(MAKEFLAGS))
MF_LONG_OPTION_REGION = $(call mf_drop_leading_long_options,$(MF_ASSIGNMENT_REGION))
MF_LONG_OPTION_LEADS = $(if $(filter $(words $(MF_ASSIGNMENT_REGION)),$(words $(MF_LONG_OPTION_REGION))),,1)
MF_FLAG_WORD = $(firstword $(MF_LONG_OPTION_REGION))
MF_FLAG_LETTERS = $(if $(filter -%,$(MF_FLAG_WORD)),$(if $(MF_LONG_OPTION_LEADS),$(subst -,,$(MF_FLAG_WORD))),$(MF_FLAG_WORD))
MF_OPTION_CLUSTER = $(if $(MF_FLAG_LETTERS),$(if $(call mf_non_option_characters,$(MF_FLAG_LETTERS)),,$(MF_FLAG_LETTERS)))
DRY_RUN = $(if $(findstring n,$(MF_OPTION_CLUSTER)),1,)

NEEDS_HOMEBREW := $(if $(filter Darwin,$(DETECTED_OS)),$(if $(shell command -v brew 2>/dev/null),,yes),)
HAVE_DOCKER_CLI := $(shell command -v docker 2>/dev/null)

CI ?= false

AUTO_INSTALL ?= true

ifdef CONDA_DEFAULT_ENV
CONDA_ENV ?= $(CONDA_DEFAULT_ENV)
else
CONDA_ENV ?= holon
endif

CONDA_ENV_ORIGIN := $(origin CONDA_ENV)
CONDA_ALLOW_BASE_ORIGIN := $(origin CONDA_ALLOW_BASE)
CONDA_ENV_REQUESTED := $(if $(or $(findstring command line,$(CONDA_ENV_ORIGIN)),$(findstring environment,$(CONDA_ENV_ORIGIN))),true,false)
CONDA_ENV_ON_COMMAND_LINE := $(if $(findstring command line,$(CONDA_ENV_ORIGIN)),true,false)
CONDA_ALLOW_BASE_REQUESTED := $(if $(filter 1 true yes,$(CONDA_ALLOW_BASE)),$(if $(findstring command line,$(CONDA_ALLOW_BASE_ORIGIN)),true,false),false)
ifeq ($(CONDA_ENV_REQUESTED),true)
CONDA_WRITE_ENV := $(CONDA_ENV)
else
CONDA_WRITE_ENV := holon
endif
CONDA_BASE_CONSENT := false
ifeq ($(CONDA_ALLOW_BASE_REQUESTED),true)
ifeq ($(and $(filter base,$(CONDA_WRITE_ENV)),$(filter environment,$(CONDA_ENV_ORIGIN))),)
CONDA_BASE_CONSENT := true
endif
endif
ifeq ($(CONDA_WRITE_ENV),base)
ifeq ($(CONDA_ENV_ON_COMMAND_LINE),true)
CONDA_BASE_CONSENT := true
endif
endif

CONDA_PROMPT_TIMEOUT ?= 20

CONDA_PRUNE ?= false
CONDA_PRUNE_EFFECTIVE := $(if $(findstring command line,$(origin CONDA_PRUNE)),$(CONDA_PRUNE),false)

ifeq ($(CI),true)
BUILD_IMAGE_ARGS ?= --output-log
else
BUILD_IMAGE_ARGS ?=
endif

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

.PHONY: check-prerequisites prerequisites check-docker install-docker install-homebrew install-miniforge create-conda-env activate-conda-env build-image build-images tools check lint lint-json lint-yaml lint-shell lint-md pre-commit-check install-hooks help

install-homebrew:
	@if [ "$(DETECTED_OS)" = "Darwin" ]; then \
		if ! command -v brew >/dev/null 2>&1; then \
			echo "Homebrew not found. Installing Homebrew..."; \
			NONINTERACTIVE=1 /bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || exit 1; \
		else \
			echo "Homebrew is already installed."; \
		fi; \
	fi

ifeq ($(NEEDS_HOMEBREW),yes)
install-docker: install-homebrew
install-miniforge: install-homebrew
endif

install-docker:
	@echo "$(COLOR_BOLD)Checking Docker installation for $(DETECTED_OS)...$(COLOR_RESET)"
	@if [ -n "$(DRY_RUN)" ]; then exit 0; \
	elif command -v docker >/dev/null 2>&1; then \
		echo "$(COLOR_GREEN)✅ Docker is already installed: $$(docker --version)$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  Docker not found. Installing Docker for $(DETECTED_OS)...$(COLOR_RESET)"; \
		if [ "$(DETECTED_OS)" = "Darwin" ]; then \
			if ! command -v brew >/dev/null 2>&1; then \
				echo "$(COLOR_RED)❌ Homebrew is not on PATH, so Docker Desktop cannot be installed.$(COLOR_RESET)"; \
				echo "   Run $(COLOR_BOLD)make install-homebrew$(COLOR_RESET) first; it also runs automatically as a prerequisite of this target."; \
				exit 1; \
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

check-docker:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	ERRORS=0; \
	printf "%-32s " "Checking Docker CLI..."; \
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

ifeq ($(AUTO_INSTALL),true)
ifeq ($(HAVE_DOCKER_CLI),)
check-docker: install-docker
endif
endif

check-prerequisites:
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) Checking Prerequisites for holon-coherence$(COLOR_RESET)"
	@echo "$(COLOR_BOLD) OS: $(DETECTED_OS) | Arch: $(DETECTED_ARCH)$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
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
	if [ -n "$$CONDA_PREFIX" ] && [ -x "$$CONDA_PREFIX/bin/uv" ] && { [ -z "$$ACTIVE_ENV" ] || [ "$$ACTIVE_ENV" = "$$TARGET_ENV" ]; }; then \
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
		echo "   npx is needed only for Prettier markdown documentation hygiene checks (advisory: this is a warning, not a failure)."; \
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

prerequisites: check-prerequisites

install-miniforge:
	@echo "$(COLOR_BOLD)Installing Miniforge for $(DETECTED_OS)...$(COLOR_RESET)"
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	$(FIND_CONDA_BIN); \
	if [ -n "$$CONDA_BIN" ]; then \
		echo "$(COLOR_GREEN)✅ Miniforge is already installed ($$CONDA_BIN).$(COLOR_RESET)"; \
	elif [ "$(DETECTED_OS)" = "Darwin" ]; then \
		if ! command -v brew >/dev/null 2>&1; then \
			echo "$(COLOR_RED)❌ Homebrew is not on PATH, so Miniforge cannot be installed.$(COLOR_RESET)"; \
			echo "   Run $(COLOR_BOLD)make install-homebrew$(COLOR_RESET) first; it also runs automatically as a prerequisite of this target."; \
			exit 1; \
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

shq = '$(subst ','\'',$(1))'

create-conda-env: install-miniforge
	@$(FIND_CONDA_BIN); \
	if [ -z "$$CONDA_BIN" ]; then \
		echo "$(COLOR_RED)❌ Conda not found after Miniforge installation.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	CHOSEN_ENV=$(call shq,$(CONDA_WRITE_ENV)); \
	BASE_CONSENT="$(CONDA_BASE_CONSENT)"; \
	PROMPT_TIMEOUT=$(call shq,$(CONDA_PROMPT_TIMEOUT)); \
	case "$$PROMPT_TIMEOUT" in ''|*[!0-9]*) echo "$(COLOR_RED)❌ CONDA_PROMPT_TIMEOUT must be a whole number of seconds.$(COLOR_RESET)"; exit 1;; esac; \
	ACTIVE_ENV="$$CONDA_DEFAULT_ENV"; \
	if [ -n "$$ACTIVE_ENV" ]; then ACTIVE_DESC="active env: $$ACTIVE_ENV"; else ACTIVE_DESC="no active conda env"; fi; \
	if [ -t 0 ] && [ "$(CI)" != "true" ] && [ "$(NONINTERACTIVE)" != "1" ] && [ "$(CONDA_ENV_ON_COMMAND_LINE)" != "true" ]; then \
		if ! printf 'y\n' | read -r -t 1 _holon_probe >/dev/null 2>&1; then \
			echo "$(COLOR_YELLOW)❌ This shell's read cannot time out, so the prompt cannot be offered safely.$(COLOR_RESET)"; \
			echo "   Nothing was installed into a conda environment: an unanswerable prompt must not be answered on your behalf, and silently picking a default is an implicit yes."; \
			echo "   (The install-miniforge prerequisite runs before this check and may have installed Miniforge itself.)"; \
			echo "   Name the environment deliberately on the command line: make create-conda-env $(COLOR_BOLD)CONDA_ENV=<name>$(COLOR_RESET); a name typed there is not prompted for."; \
			exit 1; \
		else \
			echo "$(COLOR_BOLD)====================================================$(COLOR_RESET)"; \
			echo " Holon-Coherence Conda Environment Setup"; \
			echo "$(COLOR_BOLD)====================================================$(COLOR_RESET)"; \
			echo "This will install Python and uv via Conda into the chosen environment."; \
			echo " Currently active: $$ACTIVE_DESC (press Enter to keep '$$CHOSEN_ENV')"; \
			printf "Enter target environment name [default: %s]: " "$$CHOSEN_ENV"; \
			if ! read -r -t "$$PROMPT_TIMEOUT" USER_INPUT; then \
				echo "$(COLOR_RED)❌ No answer within $$PROMPT_TIMEOUT s; nothing was installed into a conda environment.$(COLOR_RESET)"; \
				echo "   It would have provisioned conda env '$$CHOSEN_ENV' from environment.yml (active: $$ACTIVE_DESC)."; \
				echo "   Answer it deliberately, or pass the name on the command line: make create-conda-env $(COLOR_BOLD)CONDA_ENV=$$CHOSEN_ENV$(COLOR_RESET)"; \
				exit 1; \
			fi; \
			if [ -n "$$USER_INPUT" ]; then \
				CHOSEN_ENV="$$USER_INPUT"; \
			fi; \
			if [ "$$CHOSEN_ENV" = "base" ] && [ "$$BASE_CONSENT" != "true" ]; then \
				printf "'base' is a shared environment. Type 'yes' to install into it [no]: "; \
				if ! read -r -t "$$PROMPT_TIMEOUT" BASE_REPLY; then \
					echo "$(COLOR_RED)❌ No answer within $$PROMPT_TIMEOUT s; refusing to write to 'base'.$(COLOR_RESET)"; \
					echo "   It would have run: \"$$CONDA_BIN\" install -y -n base -c conda-forge uv python=3.13"; \
					exit 1; \
				fi; \
				if [ "$$BASE_REPLY" = "yes" ]; then \
					BASE_CONSENT=true; \
				else \
					echo "Aborted: 'base' was not confirmed. Pick another name or pass $(COLOR_BOLD)CONDA_ENV=base$(COLOR_RESET) deliberately."; \
					exit 1; \
				fi; \
			fi; \
		fi; \
	fi; \
	if [ -z "$$CHOSEN_ENV" ]; then \
		echo "$(COLOR_RED)❌ Empty environment name. Pass $(COLOR_BOLD)CONDA_ENV=<name>$(COLOR_RESET) or use the default 'holon'.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	case "$$CHOSEN_ENV" in -*|*[!A-Za-z0-9._-]*) echo "$(COLOR_RED)❌ Invalid environment name '$$CHOSEN_ENV': use letters, digits, '.', '_' and '-', not starting with '-'.$(COLOR_RESET)"; exit 1;; esac; \
	if [ "$$CHOSEN_ENV" = "base" ] && [ "$$BASE_CONSENT" != "true" ]; then \
		echo "$(COLOR_RED)❌ Refusing to write to 'base': this invocation did not ask for it.$(COLOR_RESET)"; \
		echo "   An inherited environment variable (CONDA_ENV=base or CONDA_ALLOW_BASE=1 in your shell) is not consent."; \
		echo "   Request it deliberately on the command line: make create-conda-env $(COLOR_BOLD)CONDA_ENV=base$(COLOR_RESET)"; \
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
			if [ "$(CONDA_PRUNE_EFFECTIVE)" = "1" ] || [ "$(CONDA_PRUNE_EFFECTIVE)" = "true" ]; then \
				CONDA_PRUNE_FLAG="--prune"; \
				echo "CONDA_PRUNE=$(CONDA_PRUNE_EFFECTIVE): pruning packages that are absent from environment.yml."; \
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

build-image: check-docker
	@echo "$(COLOR_BOLD)Building holon-coherence Docker image...$(COLOR_RESET)"
	@./build_image.sh $(BUILD_IMAGE_ARGS)

build-images: build-image

tools:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	ERRORS=0; \
	echo "$(COLOR_BOLD)OS Toolbelt Inspection:$(COLOR_RESET)"; \
	for tool in git jq shellcheck uv gh npx openssl; do \
		tool_path=$$(command -v "$$tool" 2>/dev/null || true); \
		if [ -n "$$tool_path" ]; then \
			case "$$tool" in \
				git) tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true) ;; \
				jq) tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true) ;; \
				shellcheck) tool_ver=$$("$$tool_path" --version 2>/dev/null | grep -E 'version:' | head -n 1 || true); \
					if [ -z "$$tool_ver" ]; then tool_ver=$$("$$tool_path" -V 2>/dev/null | head -n 2 | tail -n 1 || true); fi; \
					if [ -z "$$tool_ver" ]; then tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true); fi ;; \
				uv) tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true) ;; \
				gh) tool_ver=$$("$$tool_path" --version 2>/dev/null | grep -E 'gh version' | head -n 1 || true); \
					if [ -z "$$tool_ver" ]; then tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true); fi ;; \
				npx) tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true) ;; \
				openssl) tool_ver=$$("$$tool_path" version 2>/dev/null | head -n 1 || true) ;; \
				*) tool_ver=$$("$$tool_path" --version 2>/dev/null | head -n 1 || true) ;; \
			esac; \
			if [ -z "$$(printf '%s' "$$tool_ver" | tr -d '[:space:]')" ]; then tool_ver="unknown version"; fi; \
			printf "  %-12s %-35s %s\n" "$$tool" "$$tool_path" "$$tool_ver"; \
		else \
			printf "  %-12s %-35s %b\n" "$$tool" "NOT FOUND" "$(COLOR_RED)missing$(COLOR_RESET)"; \
			ERRORS=$$((ERRORS + 1)); \
		fi; \
	done; \
	if [ $$ERRORS -gt 0 ]; then \
		echo "$(COLOR_RED)❌ $$ERRORS required toolbelt tool(s) missing from PATH.$(COLOR_RESET)"; \
		exit 1; \
	else \
		echo "$(COLOR_GREEN)✅ All toolbelt tools are present.$(COLOR_RESET)"; \
	fi

install-hooks:
	@if [ -n "$(DRY_RUN)" ]; then \
		echo "$(COLOR_BOLD)Dry run: would configure git core.hooksPath to .githooks$(COLOR_RESET)"; \
		exit 0; \
	fi; \
	if [ ! -f ".githooks/commit-msg" ]; then \
		echo "$(COLOR_RED)❌ Missing .githooks/commit-msg hook.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	if [ ! -x ".githooks/commit-msg" ]; then \
		echo "$(COLOR_RED)❌ .githooks/commit-msg is not executable.$(COLOR_RESET)"; \
		exit 1; \
	fi; \
	git config core.hooksPath .githooks || exit 1; \
	echo "$(COLOR_GREEN)✅ Configured git core.hooksPath to .githooks$(COLOR_RESET)"

pre-commit-check:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	echo "$(COLOR_BOLD)Running pre-commit security and scratch file checks...$(COLOR_RESET)"; \
	if command -v uv >/dev/null 2>&1; then \
		uv run python scripts/pre_commit_check.py; \
	else \
		python3 scripts/pre_commit_check.py; \
	fi

lint-json:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking JSON formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.json" --no-error-on-unmatched-pattern; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-json$(COLOR_RESET)"; \
	fi

lint-yaml:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking YAML formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.yml" "**/*.yaml" --no-error-on-unmatched-pattern; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-yaml$(COLOR_RESET)"; \
	fi

lint-shell:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v shellcheck >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking shell scripts with shellcheck...$(COLOR_RESET)"; \
		find . -type f -name "*.sh" -not -path "*/.*/*" -not -path "./build/*" -not -path "./dist/*" -exec shellcheck {} +; \
	else \
		echo "$(COLOR_YELLOW)⚠️  shellcheck not found on PATH, skipping lint-shell$(COLOR_RESET)"; \
	fi

lint-md:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking Markdown formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.md" --no-error-on-unmatched-pattern; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-md$(COLOR_RESET)"; \
	fi

lint: pre-commit-check lint-json lint-yaml lint-shell lint-md
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v uv >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Running Python linting...$(COLOR_RESET)"; \
		uv run task lint; \
	fi

check: pre-commit-check lint

help:
	@echo "$(COLOR_BOLD)Usage:$(COLOR_RESET) make [target]"
	@echo "All targets must be executed from the root of the repository."
	@echo ""
	@echo "$(COLOR_BOLD)Available targets:$(COLOR_RESET)"
	@printf $(HELP_FORMAT) "check-prerequisites" "Check Docker, Conda, uv, OpenSSL (fatal if missing) and npx (advisory: warns only)."
	@printf $(HELP_FORMAT) "prerequisites" "Alias for check-prerequisites."
	@printf $(HELP_FORMAT) "check-docker" "Check Docker prerequisite and install Docker if missing."
	@printf $(HELP_FORMAT) "install-docker" "Install Docker for the detected operating system."
	@printf $(HELP_FORMAT) "install-homebrew" "Install Homebrew (macOS only)."
	@printf $(HELP_FORMAT) "install-miniforge" "Install Miniforge for the detected operating system."
	@printf $(HELP_FORMAT) "create-conda-env" "Create or update Conda environment (CONDA_WRITE_ENV, default 'holon'; 'base' only on deliberate consent; CONDA_PRUNE=1 to prune)."
	@printf $(HELP_FORMAT) "activate-conda-env" "Show command to activate the Conda environment."
	@printf $(HELP_FORMAT) "build-image" "Build the holon-coherence Docker container via build_image.sh."
	@printf $(HELP_FORMAT) "build-images" "Alias for build-image."
	@printf $(HELP_FORMAT) "tools" "Inspect OS toolbelt dependencies (git, jq, shellcheck, uv, gh, npx, openssl)."
	@printf $(HELP_FORMAT) "check" "Run pre-commit-check and all lint targets."
	@printf $(HELP_FORMAT) "lint" "Run all repository linting checks (Prettier, shellcheck, pre-commit)."
	@printf $(HELP_FORMAT) "lint-json" "Check JSON files with Prettier (--no-config)."
	@printf $(HELP_FORMAT) "lint-yaml" "Check YAML files with Prettier (--no-config)."
	@printf $(HELP_FORMAT) "lint-shell" "Check shell scripts with shellcheck."
	@printf $(HELP_FORMAT) "lint-md" "Check Markdown documentation with Prettier (--no-config)."
	@printf $(HELP_FORMAT) "pre-commit-check" "Run pre-commit secret leak and scratch file detection."
	@printf $(HELP_FORMAT) "install-hooks" "Verify .githooks/commit-msg and configure git core.hooksPath to .githooks."
	@printf $(HELP_FORMAT) "help" "Show this help message."
	@echo ""
	@echo "$(COLOR_BOLD)Variables:$(COLOR_RESET)"
	@printf $(HELP_FORMAT) "CONDA_ENV" "Environment to report in check-prerequisites (default: active CONDA_DEFAULT_ENV, else 'holon')."
	@printf $(HELP_FORMAT) "CONDA_WRITE_ENV" "DERIVED, not a knob: the environment create-conda-env writes to ('holon', or the CONDA_ENV you pass; never an activated 'base'). Set CONDA_ENV instead."
	@printf $(HELP_FORMAT) "CONDA_ALLOW_BASE" "Set to 1/true/yes ON THE MAKE COMMAND LINE to consent to writing into 'base'; an inherited value never grants consent."
	@printf $(HELP_FORMAT) "CONDA_PRUNE" "Set to 1 or true on the make command line to add --prune to 'conda env update' for an existing environment (default: false; a shell-exported value is ignored)."
	@printf $(HELP_FORMAT) "CONDA_PROMPT_TIMEOUT" "Seconds the interactive target prompt waits for an answer before refusing (default: 20)."
	@printf $(HELP_FORMAT) "NONINTERACTIVE" "Set to 1 to skip the interactive target prompt (also implied by CI=true or a non-terminal stdin)."
	@echo ""
