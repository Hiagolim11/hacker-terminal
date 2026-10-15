.PHONY: run diagnose check check-gui deb

DEB_OUTPUT_DIR ?= dist

run:
	./run.sh

diagnose:
	./run.sh --diagnose

check:
	./tests/smoke.sh

check-gui:
	HACKER_TERMINAL_GUI_TEST=1 ./tests/smoke.sh

deb:
	./packaging/build-deb.sh "$(DEB_OUTPUT_DIR)"
