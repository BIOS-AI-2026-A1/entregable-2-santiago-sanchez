# Plan — Outreach Agent (verificación directa con comercios)

**Estado:** Aprobado
**Aprobado por:** Santiago

## Objetivo
Cerrar el gap de los lugares en `needs_review` con evidencia insuficiente,
contactando directamente al comercio para confirmar si tiene opciones
sin TACC reales, en vez de dejarlos indefinidamente en la cola de
revisión humana — sin ceder el criterio conservador del Validator.

## Contexto
El Validator (ADR-001) frena en `needs_review` cuando la evidencia
online no alcanza el piso de confianza (0.85). Hoy esa cola crece cada
corrida y se resuelve solo manualmente. El Outreach Agent no reemplaza
ese juicio — le agrega una fuente de evidencia nueva (la respuesta
directa del comercio), que el Validator reevalúa junto con la
evidencia original (ver ADR-002 para la decisión de por qué esa
respuesta no aprueba directo).

## Diseño en dos etapas, con frecuencias distintas

### Etapa 1 — Envío (`outreach_send`)
- Corre **dentro del pipeline mensual existente**, como 7ma etapa,
  compartiendo el mismo presupuesto de agentes.
- Toma hasta `OUTREACH_MONTHLY_LIMIT` lugares en `needs_review` con
  contacto disponible (prioriza los más antiguos).
- Redacta el mensaje con Claude Haiku (mismo patrón que el Social
  agent), usando una plantilla base + el nombre/categoría del lugar.
- Envía por email (Fase 1) o WhatsApp (Fase 2, sujeto a verificación
  de Meta).
- Guarda el mensaje enviado en `outreach_messages` y actualiza
  `places.outreach_status = 'sent'`.

### Etapa 2 — Recepción e interpretación (`outreach_reply_handler`)
- **No es parte del cron mensual** — es un webhook, disparado solo
  cuando llega una respuesta real. No corre en loop, no consume nada
  si nadie responde.
- Cuando llega una respuesta, el Validator (Claude Sonnet) re-evalúa
  combinando la evidencia original con la respuesta del comercio.
- Resultado de la re-evaluación (ver ADR-002):
  - Confianza combinada alta → `places.status = 'outreach_confirmed'`
    (NO `approved` directo) — queda esperando aprobación humana final,
    con contexto ya resuelto.
  - Sigue ambiguo → vuelve a `needs_review`.
  - Sin respuesta tras el período definido en Fase 1 → permanece en
    `needs_review`, sin cambios.
- Ningún camino de outreach llega a `approved` sin aprobación humana
  explícita.

## Cambios de schema requeridos (ver ADR-002)
- `places.contact_email`, `places.contact_phone` (confirmar primero
  qué trae Google Places Details que hoy no se está persistiendo)
- `places.status`: agregar `outreach_confirmed` como valor válido del
  CHECK constraint existente (junto a pending/approved/needs_review/discarded)
- `places.outreach_status`: `not_sent` / `sent` / `replied` / `no_response`
- `places.outreach_channel`: `email` / `whatsapp`
- Tabla nueva `outreach_messages`: thread completo (mensaje enviado,
  respuesta recibida, timestamps) para auditoría

## Control de gasto
- `OUTREACH_MONTHLY_LIMIT` — techo explícito de mensajes por corrida,
  separado del presupuesto de descubrimiento/validación.
- Prioriza lugares con contacto ya disponible, para no gastar en
  intentos que van a fallar por falta de dato.

## Fases
1. **Fase 0 (ahora):** confirmar qué contacto ya trae Google Places
   Details hoy sin persistir — puede que la mitad del trabajo de
   datos ya esté a mitad de camino.
2. **Fase 1:** canal Email únicamente, envío + webhook de recepción.
   Define acá el período de espera y reintentos antes de considerar
   "sin respuesta".
3. **Fase 2:** canal WhatsApp, en paralelo iniciar verificación de
   negocio ante Meta (proceso externo, no depende de nosotros).

## Fuera de alcance por ahora
- Aprobación automática sin pasar por revisión humana final — la
  respuesta del comercio es evidencia adicional, nunca un atajo de
  confianza ciega (ver ADR-002).
- Reintentos automáticos si no hay respuesta (se define el número de
  intentos y espaciado en Fase 1).
