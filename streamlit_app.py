"""Start the complete local research platform."""
import os
os.environ.setdefault("PORTFOLIO_MODE", "local")
from portfolio_app.local_app import main
main()
