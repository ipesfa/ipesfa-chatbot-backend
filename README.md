# ipesfa-chatbot-backend

Deploy automático activo en dev (`dev.ipesfa-ushuaia.edu.ar/chat-api-dev`).

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

1. Crear la app Python en cPanel (una para dev, una para producción). **Si el
   dominio elegido ya tiene un sitio real (WordPress) en la raíz, poner
   SIEMPRE un path** (ej. `chat-api-dev`), nunca dejarlo vacío — si no, la
   Python App toma control de todo el subdominio y tumba lo que ya estaba ahí.
2. En el `.htaccess` que genera cPanel para la app, agregar `RewriteEngine Off`
   justo después del bloque de Passenger — sin esto, si el sitio WordPress de
   ese mismo dominio regenera sus reglas de reescritura (ej. al guardar
   Permalinks), su catch-all (`RewriteRule . /index.php`) puede interceptar
   las rutas de la app (`/health`, `/chat`, `/deploy-webhook`) devolviendo el
   404 de WordPress en vez de llegar a Flask.
3. Configurar variables de entorno desde la UI de cPanel (ver `.env.example`
   para la lista completa) — nunca subir `.env` al repo. **Ojo**: cPanel las
   guarda como `SetEnv` en el `.htaccess` de la app, en texto plano — nunca
   hacer `cat` completo de ese archivo, usar `grep`/`sed` acotado.
4. Dejar "Number of processes" en **1** (el rate limiting es en memoria).
5. Crear/editar el `.env` de la app en el servidor (no versionado) con, además
   de las variables normales: `WEBHOOK_SECRET=<un secreto random>` y
   `VENV_ACTIVATE=/home/USUARIO/virtualenv/RUTA_APP/3.x/bin/activate` (la ruta
   exacta la muestra cPanel al crear la app). Necesario para correr
   `reindex.py` a mano/por cron (las env vars de cPanel no llegan a una
   terminal manual) y para el endpoint de deploy automático.
6. Configurar el webhook en GitHub apuntando a
   `https://TU-DOMINIO/TU-PATH/deploy-webhook` (evento `push`, content-type
   `application/json`, mismo `WEBHOOK_SECRET`). Es una ruta de Flask
   (`app/deploy.py`), no un script PHP — un `.php` suelto en la carpeta de la
   app no se puede ejecutar porque Passenger intercepta toda esa URI.
7. Configurar un cron job semanal/quincenal corriendo
   `.../bin/python scripts/reindex.py` con `WP_BASE_URL` apuntando al sitio
   de ese entorno.
