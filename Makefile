.PHONY: up down logs pull-model test push-test-stream

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f backend

pull-model:
	./scripts/pull_model.sh $(MODEL)

test:
	pytest

push-test-stream:
	./scripts/push_test_stream.sh $(FILE)
