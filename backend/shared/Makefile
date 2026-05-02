SRC := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

build-SharedLayer:
	mkdir -p "$(ARTIFACTS_DIR)/python"
	cp -r "$(SRC)/shared" "$(ARTIFACTS_DIR)/python/"
	python3 -m pip install -r "$(SRC)/layer-requirements.txt" -t "$(ARTIFACTS_DIR)/python" --no-compile
	find "$(ARTIFACTS_DIR)/python" -type d -name __pycache__ -exec rm -rf {} +
