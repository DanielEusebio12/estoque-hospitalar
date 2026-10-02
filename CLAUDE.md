# Projeto: controle de estoque hospitalar

Stack: Python, FastAPI, SQLite (sqlite3), frontend HTML + JS puro.

Regras:
- Saldo = soma das entradas menos saídas (tabela movimentacoes). Nunca guardar saldo solto.
- Sempre usar parâmetros (?) nos SQLs.
- Validar dados com Pydantic e tratar erros com HTTPException (409, 404, 422).
- Código simples, nomes em português, comentários curtos explicando o porquê.
- Fazer só a etapa pedida, sem adiantar as próximas.
