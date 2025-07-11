lint:
	@echo "🧼 Formatting with black..."
	@black .
	@echo "✨ Linting, fixing, and sorting imports with ruff..."
	@ruff check . --fix
