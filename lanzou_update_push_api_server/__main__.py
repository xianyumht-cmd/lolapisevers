from __future__ import annotations

import uvicorn

from .config import load_config
from .server import create_app


def main() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
