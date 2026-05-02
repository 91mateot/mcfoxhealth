build-SharedLayer:
	mkdir -p "$(ARTIFACTS_DIR)/python"
	cp -r shared "$(ARTIFACTS_DIR)/python/"
	python3 -m pip install -r layer-requirements.txt -t "$(ARTIFACTS_DIR)/python" --no-compile
	find "$(ARTIFACTS_DIR)/python" -type d -name __pycache__ -exec rm -rf {} +
