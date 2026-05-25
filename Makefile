.PHONY: gen-types gen-python lint test test-unit test-contract

gen-types: gen-python
	@echo "Types generated successfully"

gen-python:
	datamodel-codegen \
		--input api/spec/openapi.yaml \
		--output xhs_growth/api/generated/models.py \
		--output-model-type pydantic_v2.BaseModel \
		--strict-types str bytes int float bool \
		--capitalize-enum-members

lint:
	ruff check xhs_growth
	ruff format xhs_growth --check

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-contract:
	pytest tests/contract/ -v