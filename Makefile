.PHONY: install lint fmt test api mock-run live-smoke proto clean-proto compile df-headless vm-provision vm-start vm-status vm-test vm-deploy vm-live-smoke

# ------------------------------------------------------------------------------
# Remote VM helpers (override via `make VAR=value`)
# ------------------------------------------------------------------------------
VM_HOST ?= 34.41.155.134
VM_USER ?= cdossman
VM_NAME ?= dfhack-host
VM_PROJECT ?= scrolller-307201
VM_ZONE ?= us-central1-a
SSH_KEY ?= $(HOME)/.ssh/google_compute_engine
SSH_OPTS ?= -i $(SSH_KEY) -o StrictHostKeyChecking=no
VM_TEST_DIR ?= ~/fort-gym-test
VM_PROD_DIR ?= /opt/fort-gym
VM_VENV_DIR ?= /opt/fort-gym/.venv
VM_LIVE_SMOKE_REF ?= main

# Git ref to test/deploy (branch, tag, or SHA)
SHA ?= origin/main

# Set LIVE=1 to enable DFHACK_LIVE tests
LIVE ?= 0

VM_SSH = ssh $(SSH_OPTS) $(VM_USER)@$(VM_HOST)
VM_GCLOUD_SSH = gcloud compute ssh $(VM_NAME) --project $(VM_PROJECT) --zone $(VM_ZONE) --command

install:
	pip install -e .[agent]

lint:
	@echo "lint placeholder"

fmt:
	@echo "fmt placeholder"

test:
	pytest -q

api:
	uvicorn fort_gym.bench.api.server:app --reload --port 8000

mock-run:
	python -c "from fort_gym.bench.run.runner import run_once; from fort_gym.bench.agent.base import RandomAgent as A; print(run_once(A(), env='mock', max_steps=3, ticks_per_step=10))"

live-smoke:
	fort-gym live-smoke

compile:
	python -m compileall -q fort_gym

proto:
	python -m fort_gym.bench.env.remote_proto.fetch_proto

clean-proto:
	rm -rf fort_gym/bench/env/remote_proto/gen

df-headless:
	./scripts/df_headless.sh

vm-provision:
	ansible-playbook -i infra/ansible/inventory.ini infra/ansible/playbooks/site.yml

vm-start:
	ansible -i infra/ansible/inventory.ini dfhack_host -b -m systemd -a "name=dfhack-headless.service state=started"
	ansible -i infra/ansible/inventory.ini dfhack_host -b -m systemd -a "name=fort-gym-api.service state=started" || true

vm-status:
	ansible -i infra/ansible/inventory.ini dfhack_host -b -m shell -a "systemctl status dfhack-headless.service fort-gym-api.service --no-pager || true"

vm-test:
	$(VM_SSH) 'cd $(VM_TEST_DIR) && git fetch origin && git checkout $(SHA) && source $(VM_VENV_DIR)/bin/activate && DFHACK_LIVE=$(LIVE) pytest -q'

vm-deploy:
	$(VM_SSH) 'set -e; sudo systemctl stop fort-gym-api || true; cd $(VM_PROD_DIR); git fetch origin; git reset --hard $(SHA); sudo systemctl start fort-gym-api; sudo systemctl status fort-gym-api --no-pager | head -n 8'

vm-live-smoke:
	$(VM_GCLOUD_SSH) 'set -euo pipefail; RUN_DIR=$$(mktemp -d /home/$(VM_USER)/fort-gym-live-smoke.XXXXXX); echo "RUN_DIR=$$RUN_DIR"; git clone --depth 1 --branch $(VM_LIVE_SMOKE_REF) https://github.com/lemoz/fort-gym.git "$$RUN_DIR" >/dev/null; cd "$$RUN_DIR"; $(VM_VENV_DIR)/bin/python -m pip install -q grpcio-tools; set -a; . /etc/fort-gym.env; set +a; export PYTHONPATH="$$RUN_DIR"; export ARTIFACTS_DIR="$$RUN_DIR/artifacts-live"; export FORT_GYM_DB_PATH="$$RUN_DIR/artifacts-live/fort_gym.sqlite3"; unset GOOGLE_API_KEY; $(VM_VENV_DIR)/bin/python -c "from fort_gym.bench.cli import app; app()" live-smoke --run-id live-dfhack-smoke'
