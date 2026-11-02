"""API entry point; the React frontend runs independently in frontend/."""

import os

from backend.api import create_app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app:app", host=os.environ.get("VOICE_SMITHS_HOST", "127.0.0.1"),
        port=int(os.environ.get("VOICE_SMITHS_PORT", "8765")), workers=1,
    )


if __name__ == "__main__":
    main()
