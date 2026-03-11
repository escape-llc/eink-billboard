import httpx
from pathlib import Path

def path_to_file_url(path):
	"""
	Converts a platform-specific file path to a properly formatted file:// URL
	using httpx for the URL joining logic.
	"""
	# 1. Use pathlib to get an absolute, properly formatted URI for the path.
	# This replaces the need for os.path.abspath and pathname2url.
	absolute_uri = Path(path).resolve().as_uri()
	
	# 2. Use httpx.URL to ensure the final result is a valid URL object
	# If the path is already an absolute URI, this just validates it.
	file_url = httpx.URL(absolute_uri)
	
	return str(file_url)
