from aiohttp import web

from webapp_server import create_web_app
from webapp_settings import WebSettings


def main() -> None:
    settings = WebSettings.from_env()
    web.run_app(create_web_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
