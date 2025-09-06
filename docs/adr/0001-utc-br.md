    # ADR 0001 — Persistir UTC, Exibir America/Sao\_Paulo

* **Status**: Accepted
* **Data**: 2025-09-06
* **Decisores**: Coordenação de Engenharia
* **Contexto**

  * O produto atende majoritariamente o Brasil, mas pode evoluir para multi‑TZ.
  * Horários **no banco** precisam ser comparáveis e não ambíguos (evitar problemas de horário de verão).
  * A UI deve exibir horas no fuso local (pt‑BR), e a API deve ser previsível.

## Decisão

1. **Persistir TODO datetime em UTC** (timezone‑aware) nas colunas `DateTime(timezone=True)`.
2. **Converter na borda**: entrada do usuário (form/API) é interpretada em `America/Sao_Paulo` por padrão; saída para UI também.
3. **Contrato de API**:

   * Requests aceitam ISO‑8601 (com TZ explícito) ou data+hora locais separados; o backend converte com helpers.
   * Responses retornam **ISO‑8601 em UTC** (sufixo `Z`) por padrão nos objetos de domínio; endpoints de UI podem opcionalmente retornar campos duplicados `*_local` quando necessário.
4. **Helpers oficiais** (aprovados): `app/utils/tz.py` com `to_utc`, `to_local`, `combine_local_to_utc`, `split_utc_to_local`, `ensure_aware_utc`, `iso_utc`.
5. **Validação**: é proibido gravar datetimes **naive** no banco; lançar `ValueError`.

## Consequências

* Comparações, ordenações e índices funcionam de forma estável (UTC).
* A UI e relatórios ficam corretos para feriados/horário de verão (ZoneInfo lida com regras da região).
* Integrações externas recebem/mandam UTC (padrão da indústria), reduzindo ambiguidade.

## Detalhes de Implementação

* **SQLAlchemy**: use `DateTime(timezone=True)`; colunas: `appointments.starts_at`, `ends_at`, `users.created_at`, `audit_logs.timestamp_utc`.
* **Pydantic/Serialização**:

  * Em modelos de resposta, priorize `UTC ISO‑8601` (ex.: `2025-09-10T17:00:00Z`).
  * Para páginas UI (Jinja) que precisam de local, converta com `to_local`.
* **Forms**: UI envia `date` + `time` locais → servidor chama `combine_local_to_utc(d, t, BR_TZ)`.
* **Testes**: `tests/test_tz_helpers.py` contendo round‑trip local↔UTC (já criado neste projeto).

## Anti‑padrões (NÃO FAZER)

* Gravar `DateTime(timezone=False)` ou strings sem TZ no banco.
* Converter para local **dentro** do domínio (services/repos). Conversão é **na borda**.
* Usar offsets fixos (ex.: `-03:00`) hardcoded; sempre use `ZoneInfo("America/Sao_Paulo")`.

## Migração / Rollout

* Ao introduzir UTC, criar migrations para ajustar colunas para `timezone=True`.
* Revisar endpoints que retornam datetimes – padronizar `Z` (UTC) e/ou adicionar campos `*_local` quando justificado.

## Referências Internas

* `app/utils/tz.py` (helpers)
* `tests/test_tz_helpers.py`
* ADR 0002 — Free/Busy
