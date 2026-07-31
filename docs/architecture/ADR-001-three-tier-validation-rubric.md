# ADR-001: Rubric de validación de tres niveles en lugar de binario

**Estado:** Aceptado

## Contexto
El Validator Agent usa Claude (Sonnet) para juzgar si un lugar es
efectivamente "sin TACC" a partir de evidencia en lenguaje natural
(reseñas, redes sociales, descripciones). Al tratarse de información
de seguridad alimentaria para personas celíacas, un falso positivo
(aprobar un lugar que no es seguro) tiene consecuencias reales para
la salud del usuario — no es un error cosmético. Un rubric binario
(aprobado/rechazado) obliga al modelo a colapsar casos ambiguos
—evidencia parcial, desactualizada, o contradictoria— hacia uno de
los dos extremos, sin manera de señalar incertidumbre real.

## Decisión
Se implementó un rubric de tres niveles con umbrales de confianza
explícitos:
- `approved` (confianza ≥ 0.85)
- `needs_review` (confianza 0.50–0.85)
- `discarded` (confianza < 0.50)

Esto requirió una migración de schema en Supabase, agregando las
columnas `needs_review` (status), `flags` (jsonb) y `recommendation`
(text) a la tabla `places`.

## Consecuencias

**Positivas:**
- Los casos ambiguos quedan explícitamente marcados para revisión
  humana en vez de forzarse a un sí/no.
- El sistema nunca "sobreestima" seguridad — el default ante la duda
  es `needs_review`, no `approved`. Esto respeta el principio
  conservador central del proyecto: nunca afirmar que algo es seguro
  sin evidencia suficiente.
- Es la base técnica para una futura escalación por niveles (Sonnet
  → Opus para los casos de menor confianza).

**Negativas / trade-offs aceptados:**
- Más complejidad de estado que un booleano simple: hay que mantener
  una cola de `needs_review` y decidir quién la resuelve (por ahora,
  revisión manual).
- El pipeline es más lento de "cerrar" — no todo lugar candidato
  termina en un estado final inmediato.
