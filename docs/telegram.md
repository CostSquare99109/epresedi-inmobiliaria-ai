# Telegram

Presentación con **python-telegram-bot** (selección única de librería). Sin SQL en los handlers: todo pasa por el orquestador y los servicios.

## Comandos

| Comando | Función |
|---|---|
| `/start` | Bienvenida + ejemplo de búsqueda natural |
| `/help` | Lista de comandos |
| `/buscar` | Guía para iniciar una búsqueda |
| `/propiedades` | Inventario disponible (vía orquestador) |
| `/favoritos` | Propiedades guardadas del usuario |
| `/busquedas` | Alertas guardadas |
| `/citas` | Visitas agendadas |
| `/perfil` | Perfil y preferencias del usuario |

El **lenguaje natural es el mecanismo principal** (`MessageHandler(TEXT & ~COMMAND)`).

## Inline keyboards

`app/bot/keyboards.py:build_keyboard` mapea las acciones del orquestador a botones (máx 2 por fila):

```
[🔎 Ver detalles] [📷 Ver fotos]
[⭐ Guardar] [⚖️ Comparar]
[📅 Agendar visita] [👤 Hablar con asesor]
[📄 Ver documentos]
```

Los botones con payload dict se serializan como `action:{json}` en `callback_data` (`parse_callback` los restaura). Los `book_slot` usan el horario como etiqueta. No se convierte todo en menús: los botones solo aportan valor.

## Fichas de propiedad

`app/bot/formatting.py:property_card` muestra: nombre, precio (+operación), área, habitaciones, baños, parqueaderos, ubicación, características, descripción, código, estado — solo datos existentes. Los ausentes: «No informado».

## Imágenes

Almacenadas localmente:

```
storage/properties/PROPERTY_ID/
├── cover.jpg
├── 001.jpg
└── 002.jpg
```

Telegram envía archivos reales (`reply_photo` con el handle del archivo). Sin URLs ficticias. El envío de fotos es tolerante a fallos (si falla, se avisa en el log y se envía el texto).

## Referencias contextuales

El orquestador resuelve «la segunda», «la de 280 millones», «la anterior», «la casa que me mostraste» mediante el estado conversacional (`conversations.state.last_results`) ANTES de llamar a las herramientas. Ejemplo:

```
Bot: Encontré 2 propiedades: 1. Casa A 2. Casa B
Usuario: la segunda
Bot: 🏠 Casa B cuesta… (ficha completa)
```

## Rate limiting

`app/security/ratelimit.py`: token bucket por usuario (Redis cuando está disponible, memoria como fallback). Límite `RATE_LIMIT_PER_MINUTE` (default 20). Excedido → mensaje «⏳ Demasiados mensajes seguidos…».

## Manejo de errores

- Cualquier excepción en un handler NO crashea el loop del bot: el orquestador captura, registra y responde con un mensaje honesto.
- Sin `TELEGRAM_BOT_TOKEN` el sistema arranca sin bot (API + workers activos) y lo avisa en el log.
- `main.py` controla el loop de polling (la app PTB no hace `run_polling` por su cuenta).
