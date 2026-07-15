.PHONY: run test lint setup-secrets research-help research-version research-validate

# 启动 GUI
run:
	python -m pa_agent.main

# 运行测试
test:
	pytest -q

# 代码检查
lint:
	ruff check . && black --check .

# 启用 pre-commit，防止 settings / 日志 / 记录被提交
setup-secrets:
	powershell -ExecutionPolicy Bypass -File tools/setup_git_secrets.ps1

# Deterministic research CLI (no GUI, LLM, credentials, or trading access)
research-help:
	python -m pa_agent.research_cli --help

research-version:
	python -m pa_agent.research_cli version

research-validate:
	python -m pa_agent.research_cli validate-environment
