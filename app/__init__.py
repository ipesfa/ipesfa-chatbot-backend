from flask import Flask
from flask_cors import CORS

from .config import Config
from .deploy import deploy_bp
from .rate_limit import limiter
from .routes import chat_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=Config.ALLOWED_ORIGINS, methods=["POST", "GET"])
    limiter.init_app(app)
    app.register_blueprint(chat_bp)
    # /deploy-webhook: lo llama GitHub server-to-server (no un browser), así
    # que no aplica CORS; tampoco se limita con el rate limit de /chat.
    app.register_blueprint(deploy_bp)

    return app
