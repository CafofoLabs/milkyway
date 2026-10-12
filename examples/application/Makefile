.PHONY: init validate plan apply

init: ## Initialize this app's independent encrypted state and provider lock
	@mkdir -p .milkyway/state
	@chmod 700 .milkyway .milkyway/state
	tofu init -input=false

validate: ## Validate configuration without applying resources
	tofu validate

plan: init ## Save an encrypted application-only plan for review
	tofu plan -out=.milkyway/application.tfplan

apply: ## Apply the existing reviewed plan; do not recalculate it
	tofu apply .milkyway/application.tfplan
