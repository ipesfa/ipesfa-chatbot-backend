# ipesfa-chatbot-backend

Backend del chatbot de consultas del sitio del IPESFA. Flask + `fastembed` (embeddings
locales en CPU) + Gemini API (free tier) para generación, con un set fijo de FAQs
que se responde sin llamar a Gemini cuando hay match de alta confianza.

Ver el plan completo de arquitectura y decisiones en el repo del tema
(`spacious-child`), memoria del proyecto IPESFA.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar GEMINI_API_KEY
python scripts/reindex.py   # genera data/*.npz a partir del sitio local
flask --app app:create_app run --debug --port 5001
```

Probar:

```bash
curl -X POST http://127.0.0.1:5001/chat \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://ipesfa-local.local' \
  -d '{"message":"¿Qué profesorados tiene el instituto?"}'
```

## FAQs

Editar `data/faqs.json` (ver esquema con un ejemplo comentado en el propio
diseño del proyecto) y correr `python scripts/reindex.py` para que se
reflejen en el matching.

## Deploy (cPanel — Setup Python App)

1. Crear la app Python en cPanel (una para dev, una para producción).
2. Configurar variables de entorno desde la UI de cPanel (ver `.env.example`
   para la lista completa) — nunca subir `.env` al repo.
3. Dejar "Number of processes" en **1** (el rate limiting es en memoria).
4. Subir `webhook-deploy.php` a la carpeta de la app, completar `$secret` y
   `$venvActivate`, y configurar el webhook en GitHub apuntando a esa URL
   (evento `push`, content-type `application/json`, mismo secreto).
5. Configurar un cron job semanal/quincenal corriendo
   `.../bin/python scripts/reindex.py` con `WP_BASE_URL` apuntando al sitio
   de ese entorno.
