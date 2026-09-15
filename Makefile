PYTHON ?= .venv/bin/python
.DEFAULT_GOAL := help
TF_ROOT ?= infra/ui-host
LOCAL_DIR ?= $(abspath .local)
CONFIG_DIR ?= $(LOCAL_DIR)/event-config
TFVARS ?= $(CONFIG_DIR)/ui-host.tfvars.json
BACKEND ?= $(LOCAL_DIR)/ui-host.tfbackend
PLAN ?= $(LOCAL_DIR)/ui-host.tfplan
PROXY_CONFIG ?= $(CONFIG_DIR)/proxy.json
MODE ?= install
EXPECTED ?=
BACKUP ?=
COMMAND_ID ?=
LOGIN_CONFIG ?= $(CONFIG_DIR)/login-bootstrap.json
ACCESS_CONFIG ?= $(CONFIG_DIR)/access.json
CARD_CONFIG ?= $(CONFIG_DIR)/shared-card.json

.PHONY: shared-status shared-plan shared-apply

shared-status:
	$(PYTHON) -m scripts.deploy_shared --proxy-config '$(PROXY_CONFIG)' --mode status --apply

shared-plan:
	$(PYTHON) -m scripts.deploy_shared --proxy-config '$(PROXY_CONFIG)' --mode '$(MODE)' --targets '$(CARD_CONFIG)' --expected '$(EXPECTED)' $(if $(BACKUP),--backup '$(BACKUP)')

shared-apply:
	$(PYTHON) -m scripts.deploy_shared --proxy-config '$(PROXY_CONFIG)' --mode '$(MODE)' --targets '$(CARD_CONFIG)' --expected '$(EXPECTED)' $(if $(BACKUP),--backup '$(BACKUP)') --apply

.PHONY: login-access-status login-access-plan login-access-apply

login-access-status:
	$(PYTHON) -m scripts.login_access --proxy-config '$(PROXY_CONFIG)' --apply

login-access-plan:
	$(PYTHON) -m scripts.login_access --proxy-config '$(PROXY_CONFIG)' --policy '$(ACCESS_CONFIG)' --expected '$(EXPECTED)'

login-access-apply:
	$(PYTHON) -m scripts.login_access --proxy-config '$(PROXY_CONFIG)' --policy '$(ACCESS_CONFIG)' --expected '$(EXPECTED)' --apply

.PHONY: help infra-init infra-plan infra-apply proxy-plan proxy-apply proxy-status proxy-result proxy-verify login-secret-plan login-secret-init login-plan login-install test

help:
	@echo "infra-init / infra-plan / infra-apply: infrastructure with a reviewed saved plan"
	@echo "proxy-plan / proxy-apply MODE=install|update|rollback: server software"
	@echo "proxy-status / proxy-result COMMAND_ID=...: remote evidence"
	@echo "proxy-verify: external HTTPS and maintenance response check"
	@echo "Updates require EXPECTED=...; rollback also requires BACKUP=..."
	@echo "login-secret-plan / login-secret-init: initialize empty login storage"
	@echo "login-plan / login-install: first loopback login installation without proxy changes"

infra-init:
	terraform -chdir='$(TF_ROOT)' init -input=false -backend-config='$(BACKEND)'

infra-plan:
	terraform -chdir='$(TF_ROOT)' validate
	terraform -chdir='$(TF_ROOT)' test
	terraform -chdir='$(TF_ROOT)' plan -input=false -var-file='$(TFVARS)' -out='$(PLAN)'

infra-apply:
	terraform -chdir='$(TF_ROOT)' apply -input=false '$(PLAN)'

proxy-plan:
	$(PYTHON) -m scripts.deploy_proxy --config '$(PROXY_CONFIG)' --mode '$(MODE)' $(if $(EXPECTED),--expected '$(EXPECTED)') $(if $(BACKUP),--backup '$(BACKUP)')

proxy-apply:
	$(PYTHON) -m scripts.deploy_proxy --config '$(PROXY_CONFIG)' --mode '$(MODE)' $(if $(EXPECTED),--expected '$(EXPECTED)') $(if $(BACKUP),--backup '$(BACKUP)') --apply

proxy-status:
	$(PYTHON) -m scripts.deploy_proxy --config '$(PROXY_CONFIG)' --mode status --apply

proxy-result:
	@test -n '$(COMMAND_ID)' || (echo 'Specify COMMAND_ID.'; exit 1)
	$(PYTHON) -m scripts.deploy_proxy --config '$(PROXY_CONFIG)' --result '$(COMMAND_ID)'

test:
	$(PYTHON) -m unittest discover -s tests -q

proxy-verify:
	$(PYTHON) -m scripts.deploy_proxy --config '$(PROXY_CONFIG)' --verify

login-secret-plan:
	$(PYTHON) -m scripts.initialize_login_secret --config '$(LOGIN_CONFIG)'

login-secret-init:
	$(PYTHON) -m scripts.initialize_login_secret --config '$(LOGIN_CONFIG)' --apply

login-plan:
	$(PYTHON) -m scripts.deploy_login --proxy-config '$(PROXY_CONFIG)' --login-config '$(LOGIN_CONFIG)'

login-install:
	$(PYTHON) -m scripts.deploy_login --proxy-config '$(PROXY_CONFIG)' --login-config '$(LOGIN_CONFIG)' --apply
