# Sistema de Agendamento Inclusivo

MVP de agendamento unificado para escolas inclusivas feito como parte do curso de bacharel em **Sistemas de Informação** para a [**Faculdade XP Educação**](https://www.xpeducacao.com.br/graduacao). O sistema foi desenvolvido como um **MVP** para a ONG [**Instituto Criativo**](https://institutocriativo.com.br/).

O projeto organiza a agenda de atendimentos especializados conectando **coordenação**, **profissionais** e **famílias/responsáveis**, com fluxos de confirmação/cancelamento, indicadores operacionais e conformidade com LGPD.

---

## Visão Geral
- **Backend** em FastAPI/SQLAlchemy com migrações Alembic e autenticação JWT.
- **Interface web** server-side (Jinja2 + CSS/JS leve) com dashboards separados por perfil.
- **Agendamentos** com prevenção de conflitos, histórico, exportação CSV e lembretes automáticos por e-mail.
- **Conformidade LGPD**: página pública de consentimento, aceite obrigatório no cadastro e trilha de auditoria.

---

## Principais Funcionalidades
- CRUD de usuários, estudantes e profissionais com papéis bem definidos.
- Painéis para família (agendamentos de alunos), profissionais (agenda semanal) e coordenação (indicadores, relatórios e visão agregada).
- Fluxo público de agendamento em múltiplos passos com confirmação e cancelamento por token.
- Exportação de relatórios da coordenação em CSV (agrupado por dia, serviço ou profissional).
- Job de lembrete T-24h que dispara e-mails com links seguros.
- Registro de consentimento LGPD e política de privacidade acessível em todo o site.

---

## Perfis de Acesso
| Perfil | Capacidades principais |
| ------ | ---------------------- |
| **Coordenação** | Gerencia usuários/profissionais, consulta disponibilidade, acompanha indicadores (`/coordination/dashboard`, `/coordination/reports`, `/coordination/overview`) e exporta CSVs. |
| **Profissional** | Mantém disponibilidade, visualiza agenda semanal, confirma/cancela atendimentos (`/professional/dashboard`, `/professional/schedule`, `/professional/week`). |
| **Família / Responsável** | Cadastra estudantes associados, agenda e acompanha atendimentos (`/family/dashboard`, `/family/appointments`). |
| **Estudante** | Tem painel de acompanhamento quando vinculado a um usuário. |

Autorização é centralizada em `app/deps.require_roles`, garantindo que cada rota/API exija os papéis corretos.

---

## Arquitetura e Stack
- **FastAPI** (`app/main.py`) organiza middlewares, roteamento e segurança (CSP, sessões, CORS, HTTPS).
- **SQLAlchemy 2.0** e **Alembic** estruturam a camada de dados (`app/models`, `alembic/versions`).
- **Jinja2** renderiza HTML e e-mails (`app/web/templates`, `app/email/templates`).
- **Estrutura de pastas** (resumo):

  ```
  app/
    api/                # Rotas REST (v1 + rotas públicas)
    web/routes/         # Páginas HTML por perfil (auth, family, professional, coordination, student)
    core/               # Configurações, segurança, logging, middlewares
    models/             # User, Student, Professional, Appointment, Tokens etc.
    schemas/            # Pydantic (entrada/saída)
    jobs/               # Rotinas (ex.: lembrete T-24h)
    services/           # Mailer e integrações auxiliares
    web/static/         # CSS, JS e assets
  scripts/              # Utilitários (ex.: `seed.py`)
  docs/adr/             # Arquivos de decisão arquitetural
  tests/                # Testes Pytest cobrindo fluxos de API e regras de negócio
  ```

- **Emails**: `app/jobs/remind_t24.py` dispara lembretes, reutilizando `app/email/render.py`.
- **Observabilidade**: logging estruturado via `structlog` (ver `app/core/logging.py`).

---

## Requisitos
- Docker 24+ e Docker Compose (ou compatível) **ou** Python 3.12 com Poetry 1.8+.
- Banco PostgreSQL 16 (provisionado automaticamente via Compose).
- Node não é necessário; front-end é renderizado no servidor.

---

## Configuração de Ambiente

### 1. Clonar o repositório
```bash
git clone https://github.com/<seu-usuario>/sistema-agendamento-inclusivo.git
cd sistema-agendamento-inclusivo
```

### 2. Variáveis de ambiente
Use o arquivo de exemplo `.env.dev` (já versionado para desenvolvimento). Ajuste conforme necessário:

```env
APP_ENV=dev
DEBUG=true
SECRET_KEY=dev-change-me
DATABASE_URL=postgresql+psycopg://app:app@db/agenda_dev
SMTP_HOST=mailhog
SMTP_PORT=1025
MAIL_FROM=no-reply@sai.local
MAIL_FROM_NAME=SAI
APP_PUBLIC_BASE_URL=http://localhost:8000
FALLBACK_REMINDER_EMAIL=seu.email@exemplo.com
```

Para produção crie um arquivo `.env` com chaves fortes (SECRET_KEY, JWT_SECRET) e URL do Postgres real.

### 3. Subir com Docker Compose (recomendado)
```bash
make up           # sobe api, db, mailhog, pgadmin e reminder-cron
make logs         # acompanha logs da API
```

Serviços expostos:
- API / UI: <http://localhost:8000>
- MailHog (visualização de e-mails): <http://localhost:8025>
- PgAdmin: <http://localhost:5050> (admin/admin)

### 4. Ambiente local via Poetry (opcional)
```bash
poetry install --no-root
poetry run uvicorn app.main:app --reload
```
Certifique-se de que o Postgres esteja disponível (ajuste `DATABASE_URL`).

---

## Banco de Dados e Migrações
- Criar/atualizar esquema:
  ```bash
  make migrate
  ```
- Gerar nova revisão (autogenerate):
  ```bash
  make makemigration MSG="descricao"
  ```
- Popular dados de exemplo:
  ```bash
  make seed              # executa scripts/seed.py (coordenação, profissionais, famílias, slots, agendas)
  ```

Migrations relevantes:
- `667634bd82ae` adiciona `COORDINATION` ao enum de roles.
- `f4a9a21d8c5e` inclui o vínculo `STUDENT` <-> `User` e amplia o enum `role_enum`.

---

## Execução de Jobs
- **Lembrete T-24h** (`app/jobs/remind_t24.py`): container `reminder-cron` roda a cada 60 s, enviando e-mails para atendimentos do dia seguinte.
- Rodar manualmente:
  ```bash
  make remind-now
  ```

---

## Testes, Qualidade e Automatizações
- **Pytest**: `make test` (ou `make run-tests` quando usando containers).
- **Linters/formatadores**: `make fmt` (Black + Isort + Ruff) e `make lint`.
- **Pre-commit**: `make precommit` instala ganchos.
- **Coleção de requisições**: `app.http` traz exemplos para VS Code / REST Client.

Testes cobrem regras de disponibilidade, cadastros por perfil, exportação de dados e políticas de autorização (`tests/test_students.py`, `tests/test_availability.py`, `tests/test_dashboard.py`, `tests/test_professionals.py`).

---

## Rotas Principais

### Interface Web
- `/login`, `/register` – Autenticação e cadastro (consentimento LGPD obrigatório).
- `/family/dashboard`, `/family/appointments`, `/family/students` – Fluxos para responsáveis.
- `/professional/dashboard`, `/professional/schedule`, `/professional/week` – Agenda e disponibilidade do profissional.
- `/coordination/dashboard`, `/coordination/reports`, `/coordination/overview` – Indicadores e relatórios; botão **Exportar CSV** aciona `/coordination/reports/export`.
- `/public/appointments/confirm/{token}` e `/public/appointments/cancel/{token}` – Fluxos públicos acionados por e-mail.

### APIs (prefixo `/api/v1`)
- `auth/login`, `auth/refresh` – Autenticação JWT.
- `appointments_wizard/*` – Passos do agendamento assistido.
- `availability/*` – Gestão de disponibilidade (coordenação/profissionais).
- `dashboard_(family|professional|coordination)` – Dados dos painéis.
- `professionals`, `students` – Gestão de cadastros.

Documentação interativa (Swagger) em `/docs` e Redoc em `/redoc`.

---

## Funcionalidades de Destaque

### Exportação CSV da Coordenação
- Endpoint `GET /coordination/reports/export` gera arquivos no formato `reports_{group_by}_{YYYYMMDD}_{YYYYMMDD}.csv`.
- Cabeçalho fixo (`label, scheduled, confirmed, attended, canceled, no_show`) e linhas separadas de acordo com o agrupamento aplicado em tela (dia, serviço ou profissional).

### Consentimento LGPD e Privacidade
- Página dedicada: `/lgpd-consent` (`app/web/templates/pages/public/lgpd_consent.html`).
- Link permanente no rodapé e modal durante o cadastro (`register.html`).
- Backend valida o aceite (`app/web/routes/auth.py:326`) antes de criar a conta.

### Timezones e Datas
- Base em UTC no banco, convertendo para `America/Sao_Paulo` nas visões (`app/utils/tz.py`, `app/web/routes/*`).
- Helpers garantem que relatórios e CSV reflitam corretamente o fuso escolhido.

### E-mail e Tokens
- Templates em `app/email/templates/`. Uso do MailHog em desenvolvimento.
- Tokens de confirmação/cancelamento armazenados em `AppointmentToken`, renovados conforme necessário.

---

## Decisões de Arquitetura
- Consulte os ADRs em `docs/adr/*.md` para histórico de decisões (timezone, mecanismo free/busy, ajustes na criação de agenda, etc.).
- `AGENTS.md` resume objetivos, papéis e orientações adicionais de design.

---

## Licença
Distribuído sob licença [Apache 2.0](LICENSE).
