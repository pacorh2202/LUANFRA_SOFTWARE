.PHONY: up down logs seed test fmt shell explorar explorar-demo

up:            ## Levanta base de datos + API + web
	docker compose up -d
	@echo "API   -> http://localhost:8000/docs"
	@echo "Web   -> http://localhost:5173"
	@echo "Adminer -> http://localhost:8080"

down:
	docker compose down

logs:
	docker compose logs -f api

seed:          ## Rellena la base con datos ficticios para desarrollar
	cd api && python scripts/sembrar_demo.py

test:
	cd api && pytest -q

fmt:
	cd api && ruff format app tests scripts && ruff check --fix app tests scripts

shell:         ## psql contra la base local
	docker compose exec db psql -U luanfra -d luanfra

explorar:      ## Explora el ERP real (necesita credenciales en .env)
	cd api && python scripts/explorar_erp.py

explorar-demo: ## Ve cómo será el informe, sin conectar a nada
	cd api && python scripts/explorar_erp.py --simular
