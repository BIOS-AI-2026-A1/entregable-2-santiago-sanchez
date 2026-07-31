# ADR-002: Respuesta de outreach como evidencia adicional, no como aprobación directa

**Estado:** Aceptado

## Contexto
El Outreach Agent contacta directamente a comercios en `needs_review`
para pedir confirmación sobre opciones sin TACC. A diferencia de las
fuentes que el Validator ya evalúa (reseñas de terceros, redes
sociales, Google Places), la respuesta del comercio viene de una
fuente con incentivo económico directo en confirmar que es seguro —
aparecer en el mapa les da visibilidad — sin que eso implique
necesariamente que entienden protocolo de contaminación cruzada o que
la respuesta sea precisa. Auto-aprobar directo desde esa respuesta
introduciría un sesgo estructural nuevo que el rubric actual (ADR-001)
no está diseñado para pesar.

## Decisión
La respuesta del comercio se reinyecta como evidencia adicional al
mismo Validator, no como una vía de aprobación paralela. El resultado
de esa re-evaluación tiene tres salidas:
- Confianza combinada alta (evidencia online + respuesta) →
  `outreach_confirmed` (nuevo estado, NO `approved` directo) — queda
  esperando aprobación humana final, pero con contexto ya resuelto en
  vez de investigación desde cero.
- Sigue ambiguo incluso con la respuesta → vuelve a `needs_review`.
- Sin respuesta tras el período definido → permanece en `needs_review`,
  sin cambios.

Ningún camino de outreach llega a `approved` sin pasar por aprobación
humana explícita.

## Consecuencias

**Positivas:**
- Cierra el gap de evidencia insuficiente sin debilitar el estándar
  de seguridad del ADR-001.
- Reduce el costo de revisión humana: `outreach_confirmed` llega con
  contexto ya resuelto, en vez de requerir investigación desde cero
  como hoy en `needs_review`.
- Mantiene una única fuente de verdad para el criterio de seguridad
  (el Validator), en vez de crear una segunda vía de decisión.

**Negativas / trade-offs aceptados:**
- No resuelve `needs_review` de forma autónoma — sigue requiriendo
  una acción humana final, aunque más liviana.
- Depende de que el comercio responda; sin período de espera y
  reintentos definidos, algunos casos podrían quedar en un limbo de
  "esperando respuesta" indefinidamente (a definir en Fase 1 del plan
  de implementación).
