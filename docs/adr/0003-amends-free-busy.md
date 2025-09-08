# ADR 0003 — Free/Busy embutido nas rotas (amends ADR-0002)
**Status**: Accepted  
**Data**: 2025-09-07  
**Amends**: ADR-0002  
**Decisores**: Coordenação de Engenharia

## Contexto
A ADR-0002 previa um serviço de domínio. Para acelerar o MVP, centralizei a lógica diretamente nas rotas.

## Decisão
- `/slots` e `/slots/local` calculam disponibilidade em UTC combinando:
  - `availability` (weekday, starts_utc/ends_utc como TIME)
  - `appointments` (`starts_at/ends_at` como TIMESTAMPTZ; ignora `CANCELLED`)
- `POST /appointments`:
  - valida sobreposição antes do insert;
  - depende de `UNIQUE(professional_id, starts_at)` para corrida;
  - violações são traduzidas para **HTTP 409**.

## Racional
- Menor atrito para entrega do MVP; menos camadas.
- Mantém coerência com TZ (UTC no banco, conversão na UI).

## Alternativas
- Serviço dedicado (FreeBusyService).
- Exclusion constraint (ver ADR futura se necessário).

## Consequências
- Um pouco mais de acoplamento nas rotas; mitigado com testes unitários de utilitários compartilhados.
- Fácil migração futura para um serviço de domínio se a complexidade aumentar.

## Plano de evolução
- Extrair utilitário/serviço quando surgirem “blackouts”, *buffers* e durations por serviço.
- Considerar `EXCLUDE USING gist` para bloqueio de qualquer sobreposição.

## Ações
- Atualizar ADR-0002 para **Amended** apontando para esta ADR.
- Garantir testes E2E: conflito (409), listagens, auditoria.
