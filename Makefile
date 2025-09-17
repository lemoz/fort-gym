.PHONY: install lint fmt test api mock-run proto clean-proto compile df-headless

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
