import uvicorn

from bookbot.admin_web import app
from bookbot.config import load_config


def main() -> None:
    config = load_config()
    uvicorn.run(
        app,
        host=config.web_host,
        port=config.web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
