import logging
import sys

# 1. Define your application's root package name (e.g., 'my_app')
APP_LOGGER_NAME = "python" 

def setup_test_logging():
	# 2. Configure the Root Logger to a high level (WARNING) 
	# This silences most third-party noise by default.
	logging.basicConfig(
			level=logging.WARNING,
			format='%(asctime)s %(levelname)s %(name)s: %(message)s',
			handlers=[logging.StreamHandler(sys.stdout)]
	)

	# 3. Explicitly set your App's Logger to a lower level (INFO or DEBUG)
	# This "whitelists" your code to show more detail than the root.
	app_logger = logging.getLogger(APP_LOGGER_NAME)
	app_logger.setLevel(logging.INFO)

	# 4. Optional: Silencing specific high-noise libraries further
	logging.getLogger("urllib3").setLevel(logging.ERROR)

# Execute the setup
setup_test_logging()

import sys
from unittest.mock import MagicMock

# Mock both the high-level and low-level modules
sys.modules["_tkinter"] = MagicMock()
sys.modules["tkinter"] = MagicMock()

# no test talks to the real internet (set EINK_TEST_LIVE=1 to let them): see python/tests/fake_internet.py
from .fake_internet import install as _install_fake_internet
_install_fake_internet()
