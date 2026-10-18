include config/config.mk

.DEFAULT_GOAL := help

# OS and Architecture Detection
DETECTED_OS := $(shell uname -s)
DETECTED_ARCH := $(shell uname -m)

# Dry-run detection, consulted by install-docker, check-docker, check-prerequisites and
# install-miniforge.
#
# Why a guard is needed at all: GNU make EXECUTES every recipe line that references $(MAKE)
# even under -n (measured on 3.81 and 4.4.1 - the whole shell command runs, so everything
# sharing that line with the recursion runs with it). These recipes probe and install, so
# they cannot leave the decision to make's own -n handling.
#
# Why the two earlier detectors were wrong: they read MAKEFLAGS, which no two makes write
# alike. Measured with `make -f probe.mk <flags> print-mf`, which echoes $(MAKEFLAGS):
#
#   flags                       GNU make 3.81                 GNU make 4.4.1
#   -n                          n                             n
#   -Bn                         nB                            Bn
#   --no-print-directory -n     " --no-print-directory -n"    "n --no-print-directory"
#   -I incdir_n                 "I incdir_n"                  " -Iincdir_n"
#   DETECTED_OS=Linux           "DETECTED_OS=Linux"           " -- DETECTED_OS=Linux"
#
# 3.81 writes long options that have no short equivalent BEFORE the compacted single-letter
# cluster, and writes that cluster with a leading dash (`-nB`); 4.x writes the cluster first
# and glues an option's value onto its flag (`-Iincdir_n`). Reading only the first word - the
# previous revision - misses 3.81's dry run completely: the long option is dropped, the
# cluster is never read, DRY_RUN stays empty and `make --no-print-directory -n check-prerequisites`
# executes every probe for real. Reading every word - the revision before that - reads an
# option's own argument as a -n, and arguments are paths: `make -I incdir_n` then reported a
# green prerequisite check that had checked nothing.
#
# The rule below drops leading long options and leading VAR=value assignments (make never
# puts a flag cluster or an option argument in front of those), consults the ONE word left at
# the front, and counts it as the cluster only when every character in it is a single-letter
# option make really accepts. So `I incdir_n`, `-Iincdir_n`, `-In` and `-j4` cannot read as a
# -n, while `n`, `nB`, `sn` and 3.81's dashed `-nI` do. A dashed word is believed only when a
# long option led, because that is the only situation any measured make writes a dashed
# cluster, and 4.x spells an include directory `-In`.
#
# These are recursive (=) on purpose: the value must be read when the recipe is expanded, not
# when this makefile is parsed. GNU make 3.81 reports a half-built MAKEFLAGS during parsing
# (`-I incdir_n` is not in it yet), which is a different string from the one the recipe's own
# sub-makes are given.
#
# What is not covered, and which way it fails: a make that spells dry run only inside a word
# this rule rejects reads as NOT a dry run, so the probes run and print during `make -n`.
# That is the harmless direction - nothing is installed, because no recipe line that installs
# references $(MAKE) any more (see the install-homebrew / install-docker prerequisites below).
# No spelling measured on 3.81 or 4.4.1 fails in that direction, and none was found that fails
# the other way; the detector is not claimed to be complete for makes that were not measured.
MF_SINGLE_LETTER_OPTIONS := b B c C d D e E f F g G h i I j k l L m n N o p q r R s S t v w W
MF_ALPHANUMERIC := a b c d e f g h i j k l m n o p q r s t u v w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 0 1 2 3 4 5 6 7 8 9

# The characters in $1 that no single-letter make option uses: non-empty means $1 is an
# option argument or an assignment, never make's compacted flag cluster.
mf_non_option_characters = $(strip $(foreach character,$(MF_ALPHANUMERIC),$(if $(findstring $(character),$(1)),$(if $(filter $(character),$(MF_SINGLE_LETTER_OPTIONS)),,$(character)))))
mf_drop_leading_long_options = $(if $(filter --%,$(firstword $(1))),$(call mf_drop_leading_long_options,$(wordlist 2,$(words $(1)),$(1))),$(1))
mf_drop_leading_assignments = $(if $(findstring =,$(firstword $(1))),$(call mf_drop_leading_assignments,$(wordlist 2,$(words $(1)),$(1))),$(1))

MF_ASSIGNMENT_REGION = $(call mf_drop_leading_assignments,$(MAKEFLAGS))
MF_LONG_OPTION_REGION = $(call mf_drop_leading_long_options,$(MF_ASSIGNMENT_REGION))
# Non-empty when long options were dropped from the front, which is when 3.81 dashes the cluster.
MF_LONG_OPTION_LEADS = $(if $(filter $(words $(MF_ASSIGNMENT_REGION)),$(words $(MF_LONG_OPTION_REGION))),,1)
MF_FLAG_WORD = $(firstword $(MF_LONG_OPTION_REGION))
MF_FLAG_LETTERS = $(if $(filter -%,$(MF_FLAG_WORD)),$(if $(MF_LONG_OPTION_LEADS),$(subst -,,$(MF_FLAG_WORD))),$(MF_FLAG_WORD))
MF_OPTION_CLUSTER = $(if $(MF_FLAG_LETTERS),$(if $(call mf_non_option_characters,$(MF_FLAG_LETTERS)),,$(MF_FLAG_LETTERS)))
DRY_RUN = $(if $(findstring n,$(MF_OPTION_CLUSTER)),1,)

# Whether the host still needs Homebrew, and whether it already has a Docker CLI. Decided
# while the makefile is read so that the installs below can express their recursion as a
# prerequisite instead of as a $(MAKE) reference inside a recipe line.
NEEDS_HOMEBREW := $(if $(filter Darwin,$(DETECTED_OS)),$(if $(shell command -v brew 2>/dev/null),,yes),)
HAVE_DOCKER_CLI := $(shell command -v docker 2>/dev/null)

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
# packages into base. It defaults to holon and tracks CONDA_ENV when that value
# was passed on the make command line or inherited from the environment, so an
# exported CONDA_ENV still names the environment this target works on.
#
# CONDA_BASE_CONSENT is the resolved answer to "may this run write into the
# shared base environment?". Consent must be given IN THIS INVOCATION, by one of:
#   - `make create-conda-env CONDA_ENV=base`   (typed on the command line),
#   - `make create-conda-env CONDA_ALLOW_BASE=1` (pre-authorises a typed choice),
#   - a typed `yes` at the interactive prompt.
# An INHERITED variable is never consent: `export CONDA_ENV=base` or
# `export CONDA_ALLOW_BASE=1` in the shell leaves CONDA_BASE_CONSENT=false and the
# recipe refuses at runtime and says why. That is why CONDA_BASE_CONSENT is named
# for the resolved decision and CONDA_ALLOW_BASE for the deliberate act.
#
# One qualification, so the wording is not over-broad: make carries command-line
# assignments into sub-makes through MAKEFLAGS, and a value that arrives that way still
# has command-line origin, so it does count as consent. `export MAKEFLAGS='CONDA_ENV=base'
# make ...` is therefore a deliberate (if obscure) act rather than inherited state. Nothing
# in this repository or .github/workflows sets MAKEFLAGS, and stripping it would break the
# sanctioned recursion (create-conda-env -> install-miniforge, check-prerequisites ->
# check-docker), so the channel stays as make defines it and the sentence is narrowed here
# instead.
CONDA_ENV_ORIGIN := $(origin CONDA_ENV)
CONDA_ALLOW_BASE_ORIGIN := $(origin CONDA_ALLOW_BASE)
CONDA_ENV_REQUESTED := $(if $(or $(findstring command line,$(CONDA_ENV_ORIGIN)),$(findstring environment,$(CONDA_ENV_ORIGIN))),true,false)
# Command-line origin only: this is the test that separates a deliberate act from inherited state.
CONDA_ENV_ON_COMMAND_LINE := $(if $(findstring command line,$(CONDA_ENV_ORIGIN)),true,false)
CONDA_ALLOW_BASE_REQUESTED := $(if $(filter 1 true yes,$(CONDA_ALLOW_BASE)),$(if $(findstring command line,$(CONDA_ALLOW_BASE_ORIGIN)),true,false),false)
ifeq ($(CONDA_ENV_REQUESTED),true)
CONDA_WRITE_ENV := $(CONDA_ENV)
else
CONDA_WRITE_ENV := holon
endif
CONDA_BASE_CONSENT := false
# CONDA_ALLOW_BASE pre-authorises a choice typed in THIS invocation. It must not turn an
# inherited `export CONDA_ENV=base` into consent: there the name was not typed, so base
# would be selected by inherited state alone (one Enter at the prompt, or no prompt at all
# in CI). The name has to be on the command line, or not base, for the flag to count.
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

# Upper bound, in seconds, for the interactive target prompt. `create-conda-env` offers
# the prompt whenever stdin is a terminal, which includes pty-backed automation; a run
# that never answers must fail fast instead of blocking forever. A timeout (or a shell
# whose `read` cannot time out) is a REFUSAL, never an implicit yes.
CONDA_PROMPT_TIMEOUT ?= 20

# Pruning an environment this target did not create can remove packages the
# user added by hand, so it is opt-in: pass CONDA_PRUNE=1 (or true).
CONDA_PRUNE ?= false
# Command-line origin only, matching CONDA_ALLOW_BASE. `--prune` removes packages that are
# absent from environment.yml from an environment this target may not have created, so the
# destructive choice must come from an act in this invocation: `CONDA_PRUNE=1 make ...` (the
# idiomatic one-off) qualifies, `export CONDA_PRUNE=1` left in the shell does not.
CONDA_PRUNE_EFFECTIVE := $(if $(findstring command line,$(origin CONDA_PRUNE)),$(CONDA_PRUNE),false)

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

.PHONY: check-prerequisites prerequisites check-docker install-docker install-homebrew install-miniforge create-conda-env activate-conda-env build-image build-images tools check lint lint-json lint-yaml lint-shell lint-md pre-commit-check help

## ==============================================================================
## Docker & Prerequisite Installation & Checks
## ==============================================================================

# Install Homebrew if not installed (macOS).
#
# Leaf installer: its recipe references no $(MAKE), which is what makes it safe to reach
# under -n. GNU make executes any recipe line that references $(MAKE) even in a dry run, so
# an installer reached that way would run for real; an installer on a line without that
# reference is only printed. The two targets that used to bootstrap Homebrew from inside
# their own installing shell command now take it as a prerequisite instead, decided when the
# makefile is read, so that their install lines contain no recursion at all.
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

# Install Docker based on operating system
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

# Check Docker prerequisite (CLI, buildx, daemon). Docker itself is installed by the
# install-docker prerequisite below, not from inside this recipe: the probe below shares one
# shell command with the buildx install further down, and a line that references $(MAKE) is
# executed even under -n, which would have run both of them during a dry run. AUTO_INSTALL
# now selects the prerequisite while the makefile is read, which is the same decision this
# target made at runtime before.
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

# Check system prerequisites: Docker (CLI, buildx, daemon), Conda, uv, OpenSSL, and npx
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

# Alias for check-prerequisites
prerequisites: check-prerequisites

# Install Miniforge based on operating system
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

# Single-quote a make value for the recipe's shell. CONDA_ENV and CONDA_PROMPT_TIMEOUT
# can come from the caller's environment, and a backtick or $( ) inside the
# double quotes the recipe used to wrap them in ran as shell code before any validation saw it.
# Inside single quotes only a single quote is special, and it is closed, escaped and reopened.
shq = '$(subst ','\'',$(1))'

# Create or update conda environment with interactive confirmation/selection
#
# The prompt is offered only when this invocation has to INVENT a name. A name typed on the
# command line is already the answer the prompt asks for, so the prompt - and with it the
# `read -t` capability probe - is skipped for it. That ordering matters twice over: the
# probe runs first in a shell, and `read` has no -t on dash (Debian/Ubuntu /bin/sh), so a
# probe placed ahead of the explicit name refused `make create-conda-env CONDA_ENV=mydev`
# on dash, which is the exact command this target's own abort text and README.md both tell
# dash users to run. Refusing is reserved for the case it belongs in: no name typed, so the
# default would be picked on the user's behalf by an unbounded read.
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

# Alias for build-image
build-images: build-image


## ==============================================================================
## Developer & Quality Toolbelt Targets
## ==============================================================================

# Inspect OS toolbelt dependencies
tools:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"; \
	echo "$(COLOR_BOLD) Inspecting OS Toolbelt Dependencies$(COLOR_RESET)"; \
	echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"; \
	for tool in git jq shellcheck uv gh npx openssl; do \
		printf "%-20s " "$$tool:"; \
		if command -v $$tool >/dev/null 2>&1; then \
			echo "$(COLOR_GREEN)✅ $$(command -v $$tool)$(COLOR_RESET)"; \
		else \
			echo "$(COLOR_YELLOW)⚠️  Not found on PATH$(COLOR_RESET)"; \
		fi; \
	done; \
	echo "$(COLOR_BOLD)=========================================$(COLOR_RESET)"

# Pre-commit credential and scratch file detection check
pre-commit-check:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	echo "$(COLOR_BOLD)Running pre-commit security and scratch file checks...$(COLOR_RESET)"; \
	if command -v uv >/dev/null 2>&1; then \
		uv run python scripts/pre_commit_check.py; \
	else \
		python3 scripts/pre_commit_check.py; \
	fi

# Check JSON formatting with Prettier
lint-json:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking JSON formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.json"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-json$(COLOR_RESET)"; \
	fi

# Check YAML formatting with Prettier
lint-yaml:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking YAML formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.yml" "**/*.yaml"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-yaml$(COLOR_RESET)"; \
	fi

# Check shell scripts with shellcheck
lint-shell:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v shellcheck >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking shell scripts with shellcheck...$(COLOR_RESET)"; \
		find . -type f -name "*.sh" -not -path "*/.*/*" -not -path "./build/*" -not -path "./dist/*" -exec shellcheck {} +; \
	else \
		echo "$(COLOR_YELLOW)⚠️  shellcheck not found on PATH, skipping lint-shell$(COLOR_RESET)"; \
	fi

# Check Markdown formatting with Prettier
lint-md:
	@if [ -n "$(DRY_RUN)" ]; then exit 0; fi; \
	if command -v npx >/dev/null 2>&1; then \
		echo "$(COLOR_BOLD)Checking Markdown formatting with Prettier...$(COLOR_RESET)"; \
		npx prettier --no-config --check "**/*.md"; \
	else \
		echo "$(COLOR_YELLOW)⚠️  npx not found on PATH, skipping lint-md$(COLOR_RESET)"; \
	fi

# Run all repository lint checks
lint: pre-commit-check lint-json lint-yaml lint-shell lint-md

# Comprehensive pre-commit and lint check
check: pre-commit-check lint


## ==============================================================================
## Help Target
## ==============================================================================

# Show this help message
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
