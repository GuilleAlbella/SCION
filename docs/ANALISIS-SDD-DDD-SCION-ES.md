# Analisis de la SPEC.md de SCION — Principios SDD y DDD

**Fecha:** 2026-05-28
**Documento analizado:** `SPEC.md` v1.21.5-spec-r10-update
**Alcance:** Evaluacion de la especificacion bajo las lentes de Spec-Driven Development (SDD) y Domain-Driven Design (DDD)

---

## 1. Evaluacion bajo Spec-Driven Development (SDD)

El SDD exige que la especificacion sea el artefacto primario que dirige toda la implementacion: especificar antes de codificar, requisitos rastreables con criterios testeables, frontera de alcance explicita, y pipeline SPECIFY → DESIGN → TASKS → EXECUTE.

### 1.1 Puntos fuertes — lo que la SPEC ya hace bien

**Especificacion-primero como contrato vivo.** El documento declara explicitamente: "Any new FR enters this document before the code" (§14.3.1). El SPEC.md vive junto al codigo, y el pipeline de CI trata desviaciones entre spec e implementacion como fallos (schema_parity test). Esto materializa el principio central del SDD de que la spec es la fuente de verdad, no el codigo.

**Requisitos con vocabulario RFC-2119.** Cada FR usa MUST / SHOULD / MAY de forma consistente (§5), lo que permite a un revisor comparar codigo contra spec y determinar conformidad objetivamente. Esto equivale al formato WHEN/THEN/SHALL del harness — el lenguaje es diferente, pero la rastreabilidad es la misma.

**Non-Goals documentados con racional.** §2.2 lista 13 non-goals (NG1–NG13), cada uno con justificacion explicita y la instruccion "Anyone proposing to relax one should engage with the rationale first". Esto cumple el principio de "Fuera del Alcance" del SDD con rigor por encima de la media.

**Golden Examples como ancla de aceptacion.** §9 define 5 ejemplos input → output esperado que funcionan simultaneamente como smoke tests y como criterios de aceptacion. Esto es exactamente lo que el SDD pide: criterios verificables e independientemente testeables.

**Scope guards inline en los FRs.** Cada FR que toca una frontera peligrosa tiene un "scope guard" explicito (ej: FR-1.1 declara "This endpoint never accepts SQL, scripts, or BTEQ files — those go to DataDNA"). Esto previene scope creep a nivel del requisito individual.

**Determinismo como propiedad de primera clase.** La spec trata idempotencia y determinismo como requisitos formales (structural_hash, diff identico para mismos inputs, schema_parity). En SDD, esto equivale a criterios de aceptacion verificables por automatizacion.

### 1.2 Brechas y oportunidades de mejora

**Ausencia de IDs rastreables por requisito individual.** Los FRs usan IDs agrupados (FR-1, FR-2, ... FR-13), pero las clausulas MUST dentro de cada FR no tienen IDs atomicos. El SDD pide rastreabilidad granular: cada clausula MUST deberia tener un ID (ej: FR-1.1-MUST-01, FR-1.1-MUST-02) para que un test pueda referenciar exactamente cual clausula valida. Hoy, el mapeo test → requisito depende de lectura humana del texto corrido.

**Criterios de aceptacion no siguen formato WHEN/THEN/SHALL.** §12 lista 10 criterios (AT-001 a AT-010), pero en formato narrativo, no estructurado. Convertir al formato del harness haria cada criterio independientemente testeable y automatizable:

```
# Hoy (narrativo):
AT-001: "Demo extract ingests, snapshot finalises, structural_hash is a 64-char hex"

# Sugerido (WHEN/THEN/SHALL):
AT-001: WHEN dict-import recibe el extract demo de 6 archivos
        THEN sistema SHALL finalizar snapshot con structural_hash de 64 caracteres hex
        AND post-ingest pipeline SHALL completar sin errores
```

**Falta un tasks.md o breakdown formal.** La SPEC cubre SPECIFY y DESIGN, pero no hay un artefacto que descomponga los FRs en tareas atomicas con dependencias, verificacion y commit asociado. El ROADMAP.md se menciona como "forward-looking plan", pero no sustituye un breakdown de tareas en formato SDD. Para features futuras (FR-1.3 usage import, §10.10 end-user testing), la ausencia de tasks.md puede generar implementacion ad-hoc.

**Sin STATE.md ni HANDOFF.md.** El documento no referencia mecanismos de persistencia de estado entre sesiones de desarrollo. Para un proyecto single-maintainer (riesgo declarado en §14.2), la ausencia de STATE.md y HANDOFF.md aumenta el bus factor. La spec reconoce el problema (§13.4 "win the lottery test") pero no adopta la solucion del SDD.

**Tests planificados sin fecha objetivo firme.** §10.10 (end-user scenario testing) y §11.5 (cross-team test plan) estan en estado "Planned — pending". El SDD exige que los tests se escriban antes de la implementacion (RED → GREEN → VERIFY). Estos tests quedaron como compromiso verbal post-Reunion 10, sin criterio de completitud.

---

## 2. Evaluacion bajo Domain-Driven Design (DDD)

El DDD organiza software en torno al dominio del problema, con lenguaje ubicuo, bounded contexts, agregados, entidades, value objects, y separacion clara entre dominio, aplicacion e infraestructura.

### 2.1 Puntos fuertes — alineamiento implicito con DDD

**Lenguaje ubicuo bien definido.** El Glosario (Appendix A) define 22 terminos de dominio con precision: Snapshot, ChangeEvent, BlastRadius, GraphNode, GraphEdge, TAISA, FK heuristic, Parser feed, etc. Estos terminos se usan consistentemente en toda la spec, en los nombres de tablas ORM (§7.1), en los endpoints (§8.1) y en los tests (§10). Esto es lenguaje ubicuo en accion — el mismo vocabulario atraviesa spec, codigo y comunicacion con stakeholders.

**Bounded Contexts implicitos y bien separados.** La spec organiza las 19 tablas ORM en 5 grupos funcionales (§7.1):

| Grupo | Tablas | Bounded Context implicito |
|---|---|---|
| Snapshot core | 8 tablas | **Contexto de Estructura** — captura y versionado del warehouse |
| Process flow | 2 tablas | **Contexto de Proceso** — flujo ETL inferido |
| Diff + impact | 5 tablas | **Contexto de Cambio** — deteccion, severidad, blast radius |
| Alerts + reasoning | 2 tablas | **Contexto de Inteligencia** — TAISA + alertas proactivas |
| Usage + criticality | 2 tablas | **Contexto de Uso** — senales de consumo y criticidad |

La separacion en modulos en el backend (`app/snapshot/`, `app/diff/`, `app/graph/`, `app/taisa/`, `app/usage/`) refleja estos contextos. Cada uno tiene su propio engine, sus modelos y su interfaz publica (§8.2).

**Agregado raiz claramente identificable.** El `Snapshot` es el agregado raiz del dominio: toda operacion relevante (diff, graph, impact, alerts, metrics) referencia un `snapshot_id`. La spec refuerza esto en FR-2: "A Snapshot is the canonical immutable representation of the warehouse at time T" y "MUST be created exclusively through the snapshot engine". Esto es exactamente el patron Aggregate Root — control de creacion centralizado, identidad unica, frontera de consistencia transaccional.

**Entidades vs Value Objects distinguibles.** La spec diferencia implicitamente:

- **Entidades** (identidad persistente): Snapshot, ChangeEvent, GraphNode, GraphEdge, ReasoningEvent — todos con IDs y ciclo de vida propio.
- **Value Objects** (identidad por valor): `structural_hash` (deterministic, content-addressed), `PaginatedResponse` envelope (§7.2), severity/is_breaking como clasificaciones inmutables de un ChangeEvent.

**Anti-corruption Layer explicita.** La frontera SCION ↔ DataDNA (§1.5) esta disenada como ACL: SCION recibe JSON del parser via `/parser-import`, valida, traduce a `graph_edge` interno, y nunca expone conceptos del parser (Tier-1/2/3) mas alla del glosario. La comunicacion es unidireccional. Esto protege el modelo de dominio de SCION contra cambios en el modelo de DataDNA.

**Domain Events como concepto de primera clase.** El `ChangeEvent` es literalmente un domain event materializado en tabla. Captura que cambio, cuando, con que severidad, y si es breaking. El pipeline post-ingest (FR-1.4) reacciona a estos eventos para generar impacto, alertas y criticidad — un flujo event-driven clasico.

**Invariantes de dominio documentadas.** La spec codifica invariantes explicitas:

- Snapshot solo se finaliza tras pipeline completo (FR-2)
- IN-clauses siempre chunked a 900 (invariante tecnica que protege el dominio de la infraestructura SQLite)
- Diff es deterministic para mismos inputs (FR-3)
- TAISA nunca recibe datos del usuario en el contexto mas alla de la pregunta (FR-6)
- Ningun endpoint produce silenciosamente output parcial (FR-13)

### 2.2 Brechas y oportunidades de mejora

**Bounded Contexts no estan nombrados explicitamente.** La separacion existe en la practica, pero la spec no usa el termino "bounded context" ni declara fronteras formales entre los modulos. Consecuencia: no hay un Context Map documentado. Quien lee la spec ve la separacion, pero no ve reglas sobre lo que ocurre cuando contextos necesitan comunicarse (ej: como el contexto de Cambio consume datos del contexto de Estructura). Documentar un Context Map evitaria acoplamiento accidental a medida que el sistema crece.

**Falta capa de Domain Services explicita.** Los "engines" (§8.2) mezclan logica de dominio pura con orquestacion de infraestructura. Por ejemplo, `compute_batch_impact` hace traversal de grafo (dominio) Y chunking de IN-clauses (infraestructura). El DDD recomendaria aislar la logica de traversal en un Domain Service puro, testeable sin base de datos, y delegar el chunking a un Repository. Hoy, el acoplamiento es tolerable por el tamano del proyecto, pero se convertira en problema en la migracion a Postgres (v1.25).

**Ausencia de Repository Pattern formal.** La spec menciona que los engines "accept an explicit Session or engine when called from tests" (§8.2), lo cual es bueno para testeabilidad, pero no declara una interfaz de repositorio abstracta. Los modelos ORM (SQLAlchemy) se usan directamente en los engines. Para la migracion a Postgres, la ausencia de Repositories puede forzar refactorizacion de los engines. El propio documento ya anticipa esto: "The portability hygiene step in v1.22 (replace INSERT OR IGNORE / strftime / julianday with ANSI equivalents) is what makes the move tractable" — pero eso es un parche de infraestructura, no una separacion de capas.

**Value Objects no estan modelados como tales.** `severity`, `change_type`, `edge_type`, `is_breaking` se tratan como strings/booleans en los modelos ORM. En DDD, estos serian Value Objects con validacion de dominio integrada (ej: severity solo acepta LOW/MEDIUM/HIGH, change_type solo acepta ADDED/DROPPED/ALTERED/RENAMED). La spec define los valores validos, pero la garantia depende de validacion en la capa de aplicacion, no en el modelo de dominio.

**Evento de dominio sin bus ni handler formal.** El `ChangeEvent` se persiste y se lee, pero no hay un mecanismo de publicacion/suscripcion entre contextos. El pipeline post-ingest (FR-1.4) es una secuencia procedural (paso 1, 2, 3, 4, 5, 6). Si un nuevo consumidor necesita reaccionar a un ChangeEvent (ej: webhook externo en el futuro, aunque hoy sea NG12), la arquitectura exigira modificar el pipeline. Un event bus interno (incluso simple, sin Kafka) daria extensibilidad sin violar el NG12.

**Modelo de proceso (process/step) poco integrado.** Las tablas `process` y `step` se mencionan en §7.1 pero no aparecen en ningun FR, ningun golden example, ningun test scenario ni ningun criterio de aceptacion. [Inferencia] Parecen un remanente de una feature planificada que no fue completamente especificada. En DDD, entidades sin caso de uso mapeado son candidatas a eliminacion o a "Fuera del Alcance" explicito.

---

## 3. Vision consolidada — Mapa de Madurez

| Dimension | Nivel actual | Objetivo recomendado | Esfuerzo |
|---|---|---|---|
| **Lenguaje ubicuo** | Alto — glosario + uso consistente | Mantener | Bajo |
| **Bounded contexts** | Medio — separacion implicita en los modulos | Nombrar y documentar Context Map | Medio |
| **Agregados** | Alto — Snapshot como raiz, creacion centralizada | Mantener | Bajo |
| **Value Objects** | Bajo — tratados como primitivos | Encapsular en clases de dominio | Medio |
| **Repositories** | Bajo — ORM directo en los engines | Abstraer interfaz antes de Postgres (v1.25) | Alto |
| **Domain Events** | Medio — ChangeEvent existe, pero pipeline procedural | Introducir handler registry simple | Medio |
| **Anti-corruption Layer** | Alto — frontera DataDNA explicita | Mantener | Bajo |
| **Rastreabilidad SDD** | Medio — FRs con MUST/SHOULD, pero sin IDs atomicos | Agregar IDs por clausula MUST | Bajo |
| **Criterios WHEN/THEN** | Bajo — formato narrativo en §12 | Convertir AT-001..010 a WHEN/THEN/SHALL | Bajo |
| **Tasks breakdown** | Ausente para features futuras | Crear tasks.md por feature a partir de v1.22 | Medio |
| **STATE/HANDOFF** | Ausente | Adoptar para mitigar bus factor | Bajo |

---

## 4. Recomendaciones priorizadas

### P1 — Hacer antes de v1.22

1. **Agregar IDs atomicos a los MUSTs de los FRs.** Pasar de "FR-1.1 bloque de texto" a "FR-1.1-M01, FR-1.1-M02, ..." permite que cada test referencie exactamente una clausula. Esfuerzo: una sesion de revision de la SPEC.

2. **Convertir AT-001..010 a formato WHEN/THEN/SHALL.** Facilita automatizacion y elimina ambiguedad en la validacion de aceptacion.

3. **Crear STATE.md en el repositorio.** Registrar decisiones recientes, blockers e ideas diferidas. El bus factor es el riesgo #1 declarado por la propia spec.

### P2 — Hacer durante v1.22–v1.24

4. **Documentar el Context Map.** Nombrar los 5 bounded contexts, declarar cuales dependen de cuales, y definir si la relacion es Shared Kernel, Customer-Supplier o Conformist.

5. **Introducir interfaces Repository** para los engines que acceden a base de datos directamente. Comenzando por el `snapshot engine` y el `impact engine` — los mas impactados por la migracion a Postgres.

6. **Encapsular Value Objects criticos.** `Severity`, `ChangeType`, `EdgeType` como enums de dominio con validacion. Esto ya existe parcialmente en los modelos Pydantic (§7.2), pero no en los modelos ORM.

### P3 — Hacer antes de v1.25 (Postgres)

7. **Separar logica de dominio de infraestructura en los engines.** Extraer el traversal de grafo, la logica de severidad, y el scoring de criticidad a funciones puras que no importen SQLAlchemy.

8. **Resolver el estado de las tablas process/step.** O especificar (FR + golden example + test) o mover a non-goals.

---

## 5. Conclusion

La SPEC.md de SCION es un documento de alta calidad que ya practica SDD en espiritu — spec-first, fronteras explicitas, non-goals documentados, golden examples como ancla. El alineamiento con DDD es fuerte en los aspectos de lenguaje ubicuo, agregados y anti-corruption layer, pero debil en la formalizacion de bounded contexts, repositories y value objects.

Las brechas mas criticas no son de concepto — son de formalizacion. El conocimiento de dominio esta en el documento; falta estructurarlo en los patrones que permiten rastreabilidad automatizada (SDD) y evolucion arquitectural segura (DDD). Las recomendaciones anteriores son incrementales y pueden adoptarse sin reescritura, lo que respeta el principio de "cambios quirurgicos" del harness.
