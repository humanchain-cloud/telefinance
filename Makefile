.PHONY: venv install initdb bot dash test check clean

PYTHON=python
VENV=.venv
ACTIVATE=. $(VENV)/bin/activate

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(ACTIVATE) && pip install --upgrade pip
	$(ACTIVATE) && pip install -r requirements.txt

initdb:
	$(ACTIVATE) && $(PYTHON) -m src.cli.init_db

bot:
	$(ACTIVATE) && $(PYTHON) -m src.cli.run_bot

dash:
	$(ACTIVATE) && streamlit run streamlit_app/app.py

test:
	$(ACTIVATE) && pytest -q

check:
	$(ACTIVATE) && python -m py_compile src/telegram_bot/handlers/service_wizard.py
	$(ACTIVATE) && python -m py_compile src/cli/run_bot.py

clean:
	rm -rf __pycache__
	rm -rf src/**/__pycache__
	rm -rf .pytest_cache