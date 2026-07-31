# Plan — Entregable 2: Prototipo con Arquitectura Documentada

**Estado:** Ejecutado
**Aprobado por:** Santiago

## Objetivo
Cumplir los 4 artefactos requeridos por el Entregable 2 sin romper
nada del pipeline ni del Entregable 1 ya completado.

## Pasos

1. **ADR-001** — Documentar la decisión del rubric de validación de
   tres niveles (approved/needs_review/discarded), por ser la
   decisión de mayor peso real del proyecto: afecta seguridad
   alimentaria de usuarios celíacos y ya está en producción.
   → `docs/architecture/ADR-001-three-tier-validation-rubric.md`

2. **Diagramas C4** — Nivel 1 (contexto) y Nivel 2 (contenedores) de
   la arquitectura actual del sistema, reflejando el estado real del
   pipeline (sin funcionalidades aún no construidas, como el chatbot).
   Primer intento con sintaxis `C4Context`/`C4Container` renderizó con
   texto superpuesto en GitHub; se resolvió migrando a `flowchart TB`
   con subgrafos, documentado como decisión en el Decisions Log.
   → `docs/architecture/C4-diagrams.md`

3. **Subagentes de Claude Code** — Dos subagentes que encapsulan
   tareas reales y recurrentes del proyecto (no inventadas para el
   entregable): migraciones de schema y mantenimiento de
   documentación de arquitectura.
   → `.claude/agents/schema-migration-agent.md`
   → `.claude/agents/architecture-docs-agent.md`

4. **Este plan** — Registrado como evidencia de trabajo plan-first,
   coherente con el flujo real de trabajo del proyecto (revisión y
   aprobación explícita antes de cada cambio).
   → `docs/plans/PLAN-entregable-2.md`

## Fuera de alcance (explícitamente pospuesto)
- Chatbot conversacional en el home — evaluado como iniciativa
  aparte, no forma parte de este entregable.
- Sistema de reseñas de usuarios — requiere auth, fuera de Fase 1
  (read-only público).
