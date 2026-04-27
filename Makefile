.PHONY: backend frontend dev install

backend:
	cd backend && python -m uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

install:
	cd frontend && npm install
	cd backend && pip install -r requirements/dev.txt
