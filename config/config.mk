HELP_FORMAT := "  %-30s - %s\n"

# Helper to locate conda binary across standard install locations and PATH
FIND_CONDA_BIN = \
	CONDA_BIN=""; \
	if command -v conda >/dev/null 2>&1; then \
		CONDA_BIN=$$(command -v conda); \
	elif [ -n "$$CONDA_EXE" ] && [ -x "$$CONDA_EXE" ]; then \
		CONDA_BIN="$$CONDA_EXE"; \
	elif [ -x "/opt/conda/bin/conda" ]; then \
		CONDA_BIN="/opt/conda/bin/conda"; \
	elif [ -x "$$HOME/miniforge3/bin/conda" ]; then \
		CONDA_BIN="$$HOME/miniforge3/bin/conda"; \
	elif [ -x "$$HOME/miniconda3/bin/conda" ]; then \
		CONDA_BIN="$$HOME/miniconda3/bin/conda"; \
	elif [ -x "/opt/homebrew/Caskroom/miniforge/base/bin/conda" ]; then \
		CONDA_BIN="/opt/homebrew/Caskroom/miniforge/base/bin/conda"; \
	elif [ -x "/usr/local/Caskroom/miniforge/base/bin/conda" ]; then \
		CONDA_BIN="/usr/local/Caskroom/miniforge/base/bin/conda"; \
	fi
