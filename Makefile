.PHONY: install lint fmt test api mock-run proto clean-proto compile df-headless vm-provision vm-start vm-status vm-test vm-deploy

# ------------------------------------------------------------------------------
# Remote VM helpers (override via `make VAR=value`)
# ------------------------------------------------------------------------------
VM_HOST ?= 34.41.155.134
VM_USER ?= cdossman
SSH_KEY ?= $(HOME)/.ssh/google_compute_engine
SSH_OPTS ?= -i $(SSH_KEY) -o StrictHostKeyChecking=no
VM_TEST_DIR ?= ~/fort-gym-test
VM_PROD_DIR ?= /opt/fort-gym
VM_VENV_DIR ?= /opt/fort-gym/.venv

# Git ref to test/deploy (branch, tag, or SHA)
SHA ?= origin/main

# Set LIVE=1 to enable DFHACK_LIVE tests
LIVE ?= 0

VM_SSH = ssh $(SSH_OPTS) $(VM_USER)@$(VM_HOST)

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
