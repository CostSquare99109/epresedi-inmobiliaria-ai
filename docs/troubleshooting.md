# Troubleshooting

## Diagnóstico general

```bash
python -m scripts.doctor
```

Muestra qué falló y cómo solucionarlo. Nunca oculta errores.

## Problemas comunes

### «pgvector no instalado»

- Termux/nativo: compilación manual (`git clone https://github.com/pgvector/pgvector && make && make install`), luego `CREATE EXTENSION vector;` en la base.

### «PostgreSQL no accesible»

- `pg_ctl -D <pgdata> start`.
- Revisa `DATABASE_URL` en `.env` (usuario/contraseña/puerto).

### «NVIDIA API ERROR» en doctor

- Crea la API key en https://build.nvidia.com y ponla en `.env` junto a `NVIDIA_MODEL`.
- El bot sigue funcionando en modo determinista (respuestas desde datos reales, sin LLM).
- Errores 401 (key inválida) y 429 (rate limit) se registran y el usuario recibe un mensaje controlado; no se inventa ninguna respuesta.

### El bot no responde en Telegram

- Verifica `TELEGRAM_BOT_TOKEN` en `.env` y que `main.py` esté corriendo (`telegram_bot_started` en el log).
- Revisa el rate limit (`RATE_LIMIT_PER_MINUTE`).
- Mira los logs: cualquier error de handler se registra sin crashear el bot.

### 401 en el panel admin

- El token admin se lee del `.env` raíz. Copia los valores: `grep -E "^(ADMIN_TOKEN|API_BASE_URL)=" ../.env > admin/.env.local` y reinicia `npm run dev`.

### El panel compila lento / primera petición tarda

- Next.js compila rutas on-demand en dev. En Termux puede tardar ~1 min por página la primera vez. Usa `npm run build && npm start` para producción.

### Termux: `next`/`tsc` no encontrados o «bad interpreter»

- Los shebangs de `node_modules/.bin` apuntan a `/usr/bin/env` (inexistente en Termux). Ejecuta directo: `node node_modules/next/dist/bin/next dev -p 3000`, `node node_modules/typescript/bin/tsc --noEmit`.

### Los tests cuelgan

- Otra sesión de pytest corriendo contra la misma BD de test produce bloqueos de tablas (el seed hace DELETE masivos). Cierra la otra sesión y reintenta.
- Verifica que PostgreSQL y Redis estén arriba.

### Los tests fallan con IntegrityError (users FK)

- Las filas de CRM/appointments referencian `users.id`: los tests deben crear el usuario primero (`memory_service.get_or_create_user`).

### Los documentos no aparecen en el RAG

- Verifica que estén en `documents/inbox/` con extensión permitida.
- Ejecuta `python -m scripts.ingest` o el botón «procesar» del panel.
- Revisa el estado del documento en el panel: FAILED muestra el error en la columna `error`.

### Redis no está disponible

- El queue hace fallback a memoria (limitación: los jobs no sobreviven reinicios). Para producción, asegúrate de que `redis-server` esté corriendo.