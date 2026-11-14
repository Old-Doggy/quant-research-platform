"""Compatibility entrypoint for older launch commands."""
import os
os.environ.setdefault("PORTFOLIO_MODE", "local")
from portfolio_app.local_app import main
if __name__ == "__main__":
 main()
