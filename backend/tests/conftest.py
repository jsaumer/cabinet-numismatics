import os
import tempfile

# Point PHOTO_DIR somewhere disposable before app.config is imported,
# so the lifespan hook doesn't create a photos/ dir in the repo.
os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))
