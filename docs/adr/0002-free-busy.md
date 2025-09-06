# ADR 0002 — Abstração Free/Busy (disponibilidade & conflitos)

* **Status**: Accepted
* **Data**: 2025-09-06
* **Decisores**: Coordenação de Engenharia
* **Contexto**

  * Precisamos oferecer uma visão de “horários livres/ocupados” por profissional/serviço, com geração de slots e prevenção de conflitos.
  * Já existe a tabela `availability` (recorrência semanal em UTC) e `appointments` com `UniqueConstraint(professional_id, starts_at_utc)`.

## Decisão

1. **Camada de serviço** `FreeBusyService` com duas capacidades principais:

   * **`free_slots(professional_id, from_utc, to_utc, slot_minutes)`**: retorna slots livres (UTC) respeitando availability, feriados/blackouts e conflitos com appointments.
   * **`is_free(professional_id, range_utc)`**: valida atomicamente se há disponibilidade no intervalo.
2. **Contrato de API** (futuro, estável):

   * `GET /availability/free-busy?professional_id=...&from=...&to=...&slot=30m` → `{ slots: ["2025-09-10T14:00:00Z", ...] }`.
   * `POST /appointments` deve validar `is_free()` **antes** de criar; o `UniqueConstraint` garante integridade sob corrida.
3. **Politicas de negócio**:

   * Slot é livre se: (a) contido em uma janela semanal disponível **E** (b) não colide com nenhum `appointment` **E** (c) não cai em `blackout`. (Blackout = tabela futura opcional `unavailability` por profissional/data.)
   * Durations padrão por serviço podem existir (futuro); por ora usamos `slot_minutes` informado.
4. **TZ**: toda a lógica roda em **UTC**; UI converte slots para local com `to_local` (ADR‑0001).

## Consequências

* API previsível e escalável; o domínio de conflito fica claro (DB + Service).
* O `UniqueConstraint` cobre concorrência mesmo com múltiplas réplicas.

## Esboço de Implementação

### Serviço (domínio)

```python
# app/services/freebusy.py
from __future__ import annotations
from datetime import datetime, timedelta, time
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.appointment import Appointment
from app.models.availability import Availability

class FreeBusyService:
    def __init__(self, db: Session):
        self.db = db

    def free_slots(self, professional_id: int, start_utc: datetime, end_utc: datetime, slot_minutes: int) -> List[datetime]:
        # 1) Carrega availability do profissional
        avails = self.db.query(Availability).filter(Availability.professional_id == professional_id).all()
        by_weekday = {}
        for a in avails:
            by_weekday.setdefault(a.weekday, []).append((a.start_utc, a.end_utc))

        # 2) Carrega appointments no range
        appts = self.db.query(Appointment).filter(
            and_(Appointment.professional_id == professional_id,
                 Appointment.starts_at_utc < end_utc,
                 Appointment.ends_at_utc > start_utc)
        ).all()
        busy = [(ap.starts_at_utc, ap.ends_at_utc) for ap in appts]

        # 3) Gera slots contidos nas janelas de availability
        step = timedelta(minutes=slot_minutes)
        cur = start_utc
        out: List[datetime] = []
        while cur + step <= end_utc:
            wd = cur.weekday()  # 0=segunda
            day_avails = by_weekday.get(wd, [])
            # slot cabe em alguma janela do dia?
            fits_avail = any((cur.time() >= a_start and (cur + step).time() <= a_end) for (a_start, a_end) in day_avails)
            if not fits_avail:
                cur += step
                continue
            # colisão com busy?
            collides = any(not ((cur + step) <= b_start or cur >= b_end) for (b_start, b_end) in busy)
            if not collides:
                out.append(cur)
            cur += step
        return out

    def is_free(self, professional_id: int, start_utc: datetime, end_utc: datetime) -> bool:
        # True se não existe appointment overlapping no intervalo
        exists = self.db.query(Appointment.id).filter(
            and_(Appointment.professional_id == professional_id,
                 Appointment.starts_at_utc < end_utc,
                 Appointment.ends_at_utc > start_utc)
        ).first() is not None
        return not exists
```

> Observação: os `Availability.start_utc/end_utc` são **time** do dia em UTC; por isso comparamos `cur.time()`.

### Índices

* Já temos índices em `appointments(professional_id, starts_at_utc)` e `ends_at_utc` pode ser considerado para janelas muito grandes.
* Para `availability`, como PK é composta, não precisa de índice extra; consultas por `professional_id` usam a PK.

### Erros e Corridas

* Antes de `INSERT appointments`, sempre chamar `is_free()`. Em caso de corrida, o `UniqueConstraint(professional_id, starts_at_utc)` ou outra unique por par `(prof, start)` falha com 23505; capturar e traduzir para 409 Conflict.

## Contratos de API (proposta)

```http
GET /availability/free-busy?professional_id=10&from=2025-09-10T00:00:00Z&to=2025-09-11T00:00:00Z&slot=30
200 { "slots": ["2025-09-10T14:00:00Z", "2025-09-10T14:30:00Z", ...] }

POST /appointments
{ "student_id": 1, "professional_id": 10, "starts_at_utc": "2025-09-10T14:00:00Z", "ends_at_utc": "2025-09-10T14:30:00Z" }
201 {...}
409 { "detail": "Horário indisponível" }
```

## Alternativas Consideradas

* Persistir em local‑time: descartado — ambiguidade e complexidade em DST.
* Calcular free/busy sempre on‑the‑fly via SQL puro (CTEs complexas): possível, mas reduz legibilidade do domínio; a abordagem em serviço facilita evolução (blackouts, buffers, durations por serviço, etc.).

## Plano de Evolução

* **Blackouts** por profissional (tabela `unavailability` com ranges em UTC).
* **Buffers** antes/depois do atendimento (minutos configuráveis por serviço/profissional).
* **Durations por serviço** com múltiplos tamanhos (p.ex. 30/45/60min) e calendário visual de slots.
* **Cache** de slots (curto prazo, por profissional/dia) para aliviar consultas repetidas.

## Referências Internas

* Tabelas: `availability`, `appointments`.
* Helpers TZ: ADR‑0001 / `app/utils/tz.py`.
* Serviço: `app/services/freebusy.py` (esqueleto acima).
