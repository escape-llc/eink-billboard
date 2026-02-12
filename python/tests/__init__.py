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
